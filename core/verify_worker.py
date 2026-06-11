"""Background worker that auto-verifies media content using the Anthropic Claude API.

Communicates **exclusively** via signals — no GUI code lives here.
"""
from __future__ import annotations
import json
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


class VerifyWorker(QThread):
    """Background thread that verifies unverified media via the Claude API.

    For each unverified video, sends the video title and the user's
    community description to Claude.  If Claude responds "YES", the
    video is marked as verified in the database.

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
        Emitted when no Anthropic API key is configured.
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
        if not ANTHROPIC_AVAILABLE:
            self.error.emit(
                "The 'anthropic' Python package is not installed. "
                "Install it with: pip install anthropic"
            )
            return

        # Read the Anthropic API key directly from settings, bypassing
        # load_api_keys which may reject the dict when YouTube/Twitch
        # keys are absent.
        raw = self._db.get_global_setting("api_keys_json") or "{}"
        try:
            parsed = json.loads(raw)
            api_key = parsed.get("anthropic", "").strip() if isinstance(parsed, dict) else ""
        except (json.JSONDecodeError, AttributeError):
            api_key = ""
        if not api_key:
            self.api_key_missing.emit()
            return

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

        client = anthropic.Anthropic(api_key=api_key)
        verified_count = 0
        use_temperature = self._model.startswith("claude-haiku")

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

            # Build API call kwargs.
            create_kwargs: dict[str, Any] = {
                "model": self._model,
                "max_tokens": 10,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_message}],
            }
            if use_temperature:
                create_kwargs["temperature"] = 0

            # Call Claude with retry on rate-limit errors.
            response_text = self._call_with_retry(client, create_kwargs, i, title)
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

        self.done.emit(verified_count)

    def _call_with_retry(
        self,
        client: anthropic.Anthropic,
        create_kwargs: dict[str, Any],
        index: int,
        title: str,
    ) -> str | None:
        """Call the Claude API with exponential backoff on rate-limit errors.

        Returns the response text on success, or ``None`` if a fatal
        error was emitted (authentication, network, etc.).
        """
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