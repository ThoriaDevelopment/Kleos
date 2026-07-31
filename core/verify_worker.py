"""Background worker that auto-verifies media content using the Anthropic
Claude API or Google Gemini API.

Communicates **exclusively** via signals — no GUI code lives here.
"""
from __future__ import annotations
import logging
import threading
import time
from typing import Any
from PyQt6.QtCore import QThread, pyqtSignal

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from google import genai as google_genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

from .ai_client import call_ai, is_gemini_model, load_ai_api_key
from .db_manager import DatabaseManager
from .local_llm import is_local_model

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a content moderator for an online community. The community "
    "describes itself as follows:\n\n\"{community_description}\"\n\n"
    "Your task is to determine whether a given video is relevant and "
    "appropriate for this community. A video \"fits\" the community if "
    "its title, description, and topic align with the community's focus, "
    "values, or subject matter.\n\n"
    "Respond with ONLY \"YES\" or \"NO\". Do not provide any explanation "
    "or additional text."
)

# Delay between consecutive API calls to avoid hitting rate limits.
# Gemini free tier is much stricter — needs a longer pause between requests.
_REQUEST_DELAY_ANTHROPIC = 0.5
_REQUEST_DELAY_GEMINI = 8.0


class VerifyWorker(QThread):
    """Background thread that verifies unverified media via Claude or Gemini.

    For each unverified video, sends the video title and the user's
    community description to the selected AI provider.  If the response
    starts with "YES", the video is marked as verified in the database.

    The AI provider is determined by the model ID prefix:
    - ``claude-`` → Anthropic Claude API
    - ``gemini-`` → Google Gemini API

    Signals
    -------
    progress(int, int)
        Current video index (1-based) and total count.
    progress_text(str)
        Human-readable status like "Verifying 12/47 videos…".
    video_verified(str)
        Emitted when a video is newly verified (carries content_id).
    done(int)
        Emitted when verification completes (carries verified count).
    error(str)
        Emitted on fatal errors (bad API key, network failure, etc.).
    api_key_missing()
        Emitted when no API key is configured.
    aborted()
        Emitted when the worker aborts due to a profile switch.
    """

    progress = pyqtSignal(int, int)
    progress_text = pyqtSignal(str)
    video_verified = pyqtSignal(str)
    done = pyqtSignal(int)
    error = pyqtSignal(str)
    api_key_missing = pyqtSignal()
    aborted = pyqtSignal()

    def __init__(
        self,
        db: DatabaseManager,
        community_description: str,
        model: str,
        parent: Any | None = None,
        creator_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._community_description = community_description
        self._model = model
        self._creator_id = creator_id
        self._cancel = threading.Event()
        self._expected_profile = ''

    def cancel(self) -> None:
        """Request the worker to stop at the next opportunity."""
        self._cancel.set()

    def run(self) -> None:
        is_gemini = is_gemini_model(self._model)
        is_local = is_local_model(self._model)

        # Check that the required SDK is installed (local models use Ollama
        # instead — no SDK, no key).  The SDK check is in-process (no network);
        # local skips it and lets call_ai surface "Ollama is not running" on the
        # first request, avoiding an extra /api/tags round-trip.
        if not is_local:
            if is_gemini:
                if not GEMINI_AVAILABLE:
                    self.error.emit(
                        "The 'google-genai' Python package is not installed. "
                        "Install it with: pip install google-genai"
                    )
                    return
            elif not ANTHROPIC_AVAILABLE:
                self.error.emit(
                    "The 'anthropic' Python package is not installed. "
                    "Install it with: pip install anthropic"
                )
                return

        # Read the appropriate API key (shared loader — same logic the
        # Discover AI workers use, so the key source stays consistent).  Local
        # models need no key, so skip the load entirely (no sentinel).
        if is_local:
            api_key = ""
        else:
            api_key, _err = load_ai_api_key(self._db, self._model)
            if not api_key:
                self.api_key_missing.emit()
                return

        # Build the system prompt.
        system_prompt = _SYSTEM_PROMPT.format(
            community_description=self._community_description.replace('{', '{{').replace('}', '}}')
        )

        # Only evaluate unverified videos (optionally scoped to one creator).
        unverified = self._db.get_unverified_media(creator_id=self._creator_id)
        total = len(unverified)
        if total == 0:
            self.done.emit(0)
            return

        # Snapshot the active profile so we can detect mid-run switches.
        self._expected_profile = self._db.current_profile

        verified_count = 0

        try:
            for i, row in enumerate(unverified, start=1):
                if self._cancel.is_set():
                    break

                # Abort if the user switched profiles mid-verification.
                if self._db.current_profile != self._expected_profile:
                    logger.warning(
                        'Profile changed from \'%s\' to \'%s\' during verification — aborting.',
                        self._expected_profile, self._db.current_profile,
                    )
                    self.aborted.emit()
                    return

                self.progress.emit(i, total)
                self.progress_text.emit(f"Verifying {i}/{total} videos…")

                content_id = row["content_id"]
                title = row["title"] or "(untitled)"
                description = row.get("description", "") or ""

                user_message = f'Video title: "{title}"\n\n'
                if description:
                    user_message += f'Description: "{description}"\n\n'
                user_message += "Does this video fit the community described above?"

                # Dispatch to the provider via the shared helper.  call_ai handles
                # retries, rate-limit backoff, auth/network errors, and (for local)
                # the Ollama host — so this worker no longer keeps its own
                # per-provider call methods.  max_tokens=10 matches the YES/NO task.
                response_text, err = call_ai(
                    model=self._model,
                    system_prompt=system_prompt,
                    user_message=user_message,
                    api_key=api_key,
                    max_tokens=10,
                    cancel_check=self._cancel.is_set,
                    db=self._db,
                )

                if response_text is None:
                    if err:
                        # Fatal error from the provider.
                        self.error.emit(err)
                        return
                    # Cancelled mid-call — fall through to done.emit().
                    break

                if self._cancel.is_set():
                    break

                if response_text.strip().upper().startswith("YES"):
                    # Atomic profile guard + write: set_verified_if_profile checks
                    # the profile and updates the row under a single lock so a
                    # switch_profile can't redirect the write into the wrong DB.
                    if not self._db.set_verified_if_profile(content_id, True, self._expected_profile):
                        logger.warning(
                            'Profile changed from \'%s\' during verification — aborting.',
                            self._expected_profile,
                        )
                        self.aborted.emit()
                        return
                    self.video_verified.emit(content_id)
                    verified_count += 1

                # Pace requests to avoid hitting rate limits.
                # Local models run locally — no rate limit, no pacing.
                if i < total and not self._cancel.is_set():
                    if is_local:
                        delay = 0
                    else:
                        delay = _REQUEST_DELAY_GEMINI if is_gemini else _REQUEST_DELAY_ANTHROPIC
                    if delay > 0:
                        end_time = time.monotonic() + delay
                        while time.monotonic() < end_time:
                            if self._cancel.is_set():
                                break
                            time.sleep(0.1)
        except RuntimeError:
            # The database was closed under us during shutdown — fail quiet
            # instead of raising an unhandled worker-thread exception.
            logger.debug('VerifyWorker aborted: database closed during shutdown.')
            return

        self.done.emit(verified_count)