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
    from google.genai import types as genai_types
    from google.genai import errors as genai_errors
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

from .ai_client import is_gemini_model, load_ai_api_key
from .db_manager import DatabaseManager

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

_MAX_RETRIES = 3
_RETRY_DELAYS = (1.0, 2.0, 4.0)
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
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._community_description = community_description
        self._model = model
        self._cancel = threading.Event()
        self._expected_profile = ''

    def cancel(self) -> None:
        """Request the worker to stop at the next opportunity."""
        self._cancel.set()

    def run(self) -> None:
        is_gemini = is_gemini_model(self._model)

        # Check that the required SDK is installed.
        if is_gemini:
            if not GEMINI_AVAILABLE:
                self.error.emit(
                    "The 'google-genai' Python package is not installed. "
                    "Install it with: pip install google-genai"
                )
                return
        else:
            if not ANTHROPIC_AVAILABLE:
                self.error.emit(
                    "The 'anthropic' Python package is not installed. "
                    "Install it with: pip install anthropic"
                )
                return

        # Read the appropriate API key (shared loader — same logic the
        # Discover AI workers use, so the key source stays consistent).
        api_key, _err = load_ai_api_key(self._db, self._model)
        if not api_key:
            self.api_key_missing.emit()
            return

        # Build the system prompt.
        system_prompt = _SYSTEM_PROMPT.format(
            community_description=self._community_description.replace('{', '{{').replace('}', '}}')
        )

        # Only evaluate unverified videos.
        unverified = self._db.get_unverified_media()
        total = len(unverified)
        if total == 0:
            self.done.emit(0)
            return

        # Snapshot the active profile so we can detect mid-run switches.
        self._expected_profile = self._db.current_profile

        # Create the appropriate client.
        if is_gemini:
            client = google_genai.Client(api_key=api_key)
        else:
            client = anthropic.Anthropic(api_key=api_key)

        verified_count = 0

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

            # Dispatch to the correct provider.
            if is_gemini:
                response_text = self._call_gemini(
                    client, system_prompt, user_message, i, title
                )
            else:
                response_text = self._call_anthropic(
                    client, system_prompt, user_message, i, title
                )

            if response_text is None:
                if self._cancel.is_set():
                    # Cancelled mid-retry — fall through to done.emit()
                    break
                # Fatal error already emitted; abort.
                return

            if self._cancel.is_set():
                break

            if response_text.strip().upper().startswith("YES"):
                # Cooperative guard: verify the profile hasn't changed
                # before writing to the database, preventing cross-profile
                # data corruption.
                if self._db.current_profile != self._expected_profile:
                    logger.warning(
                        'Profile changed from \'%s\' to \'%s\' during verification — aborting.',
                        self._expected_profile, self._db.current_profile,
                    )
                    self.aborted.emit()
                    return
                self._db.set_verified(content_id, True)
                self.video_verified.emit(content_id)
                verified_count += 1

            # Pace requests to avoid hitting rate limits.
            # Sleep between videos, but not after the last one.
            if i < total and not self._cancel.is_set():
                delay = _REQUEST_DELAY_GEMINI if is_gemini else _REQUEST_DELAY_ANTHROPIC
                if delay > 0:
                    end_time = time.monotonic() + delay
                    while time.monotonic() < end_time:
                        if self._cancel.is_set():
                            break
                        time.sleep(0.1)

        self.done.emit(verified_count)

    # ── Anthropic (Claude) ─────────────────────────────────────────────

    def _call_anthropic(
        self,
        client: anthropic.Anthropic,
        system_prompt: str,
        user_message: str,
        index: int,
        title: str,
    ) -> str | None:
        """Call the Anthropic Claude API with exponential backoff on rate-limit errors.

        Returns the response text on success, or ``None`` if a fatal
        error was emitted (authentication, network, etc.).
        """
        create_kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 10,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        }
        if self._model.startswith("claude-haiku"):
            create_kwargs["temperature"] = 0

        for attempt in range(_MAX_RETRIES + 1):
            if self._cancel.is_set():
                return None
            try:
                response = client.messages.create(**create_kwargs)
                return response.content[0].text
            except anthropic.AuthenticationError:
                self.error.emit(
                    "Invalid Anthropic API key. "
                    "Please check your key in Settings → API Keys."
                )
                return None
            except anthropic.RateLimitError:
                if attempt < _MAX_RETRIES:
                    delay = _RETRY_DELAYS[attempt]
                    logger.info(
                        "Rate limited on video %d (%s), retrying in %.1fs",
                        index, title, delay,
                    )
                    # Sleep in small increments so cancel is responsive.
                    end_time = time.monotonic() + delay
                    while time.monotonic() < end_time:
                        if self._cancel.is_set():
                            return None
                        time.sleep(0.1)
                else:
                    self.error.emit(
                        "Anthropic API rate limit exceeded. "
                        "Please wait a moment and try again."
                    )
                    return None
            except anthropic.APIConnectionError:
                self.error.emit(
                    "Network error connecting to Anthropic. "
                    "Check your internet connection."
                )
                return None
            except anthropic.APIStatusError as exc:
                self.error.emit(f"Anthropic API error: {exc}")
                return None
            except anthropic.APITimeoutError:
                self.error.emit(
                    "Anthropic API request timed out. "
                    "Check your internet connection and try again."
                )
                return None
            except anthropic.BadRequestError as exc:
                self.error.emit(f"Anthropic request error: {exc}")
                return None
            except Exception as exc:
                self.error.emit(f"Unexpected error during verification: {exc}")
                return None

    # ── Google Gemini ──────────────────────────────────────────────────

    def _call_gemini(
        self,
        client: Any,
        system_prompt: str,
        user_message: str,
        index: int,
        title: str,
    ) -> str | None:
        """Call the Google Gemini API with exponential backoff on rate-limit errors.

        Returns the response text on success, or ``None`` if a fatal
        error was emitted (authentication, network, etc.).
        """
        config = genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=10,
            temperature=0,
        )
        # Longer retry delays for Gemini free-tier rate limits.
        # Gemini resets rate limits per-minute, so we need to wait long
        # enough for the window to roll over before retrying.
        _gemini_retry_delays = (10.0, 30.0, 60.0)

        for attempt in range(_MAX_RETRIES + 1):
            if self._cancel.is_set():
                return None
            try:
                response = client.models.generate_content(
                    model=self._model,
                    contents=user_message,
                    config=config,
                )
                return response.text
            except genai_errors.APIError as exc:
                code = getattr(exc, 'code', None) or 0
                if code in (401, 403):
                    self.error.emit(
                        "Invalid Gemini API key. "
                        "Please check your key in Settings → API Keys."
                    )
                    return None
                if code == 429:
                    # Rate limit — retry with exponential backoff
                    if attempt < _MAX_RETRIES:
                        delay = _gemini_retry_delays[attempt]
                        logger.info(
                            "Gemini rate limited on video %d (%s), retrying in %.1fs",
                            index, title, delay,
                        )
                        end_time = time.monotonic() + delay
                        while time.monotonic() < end_time:
                            if self._cancel.is_set():
                                return None
                            time.sleep(0.1)
                    else:
                        self.error.emit(
                            "Gemini API rate limit exceeded. "
                            "Please wait a moment and try again."
                        )
                        return None
                else:
                    self.error.emit(f"Gemini API error: {exc}")
                    return None
            except ConnectionError:
                self.error.emit(
                    "Network error connecting to Gemini. "
                    "Check your internet connection."
                )
                return None
            except Exception as exc:
                self.error.emit(f"Unexpected error during verification: {exc}")
                return None