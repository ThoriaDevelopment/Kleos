"""Background worker that verifies media content by matching keywords
against video titles and descriptions — no AI required.

Keywords are stored as a comma-separated string in the per-profile setting
``verify_keywords``.  Each keyword is matched as a case-insensitive whole
word (or whole phrase for multi-word keywords).  If ANY keyword matches
the title or description of an unverified video, that video is marked as
verified.

Communicates **exclusively** via signals — no GUI code lives here.
"""
from __future__ import annotations
import logging
import re
import threading
from typing import Any
from PyQt6.QtCore import QThread, pyqtSignal

from .db_manager import DatabaseManager

logger = logging.getLogger(__name__)


def _keyword_to_pattern(keyword: str) -> re.Pattern[str]:
    """Compile a keyword into a case-insensitive whole-word regex.

    Single words get ``\\b`` boundaries on both sides.  Multi-word keywords
    (e.g. ``"ArchMC Network"``) allow flexible whitespace between words
    while still requiring word boundaries at the start and end.

    Examples::

        _keyword_to_pattern("arch.mc")   →  \\barch\\.mc\\b  (re.IGNORECASE)
        _keyword_to_pattern("ArchMC")    →  \\bArchMC\\b       (re.IGNORECASE)
        _keyword_to_pattern("ArchMC Network") → \\bArchMC\\s+Network\\b
    """
    words = keyword.strip().split()
    if not words:
        # Empty keyword — compile a pattern that never matches.
        return re.compile(r'(?!.*)', re.IGNORECASE)
    escaped = [re.escape(w) for w in words]
    inner = r'\s+'.join(escaped)
    return re.compile(rf'\b{inner}\b', re.IGNORECASE)


class KeywordVerifyWorker(QThread):
    """Background thread that verifies unverified media via keyword matching.

    For each unverified video, checks the title and description against
    the user's keyword list.  If any keyword matches as a whole word
    (case-insensitive), the video is marked as verified.

    Signals
    -------
    progress(int, int)
        Current video index (1-based) and total count.
    progress_text(str)
        Human-readable status like "Checking 5/13 videos…".
    video_verified(str)
        Emitted when a video is newly verified (carries content_id).
    done(int, int)
        Emitted when verification completes.  Carries ``(verified_count, total)``.
    aborted()
        Emitted when the worker aborts due to a profile switch.
    """

    progress = pyqtSignal(int, int)
    progress_text = pyqtSignal(str)
    video_verified = pyqtSignal(str)
    done = pyqtSignal(int, int)
    aborted = pyqtSignal()

    def __init__(
        self,
        db: DatabaseManager,
        keywords: list[str],
        parent: Any | None = None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._keywords = keywords
        self._cancel = threading.Event()
        self._expected_profile = ''

    def cancel(self) -> None:
        """Request the worker to stop at the next opportunity."""
        self._cancel.set()

    def run(self) -> None:
        if not self._keywords:
            self.done.emit(0, 0)
            return

        # Snapshot the active profile so we can detect mid-run switches.
        self._expected_profile = self._db.current_profile

        # Pre-compile all keyword patterns for efficiency.
        patterns = [_keyword_to_pattern(kw) for kw in self._keywords if kw.strip()]

        if not patterns:
            self.done.emit(0, 0)
            return

        unverified = self._db.get_unverified_media()
        total = len(unverified)
        if total == 0:
            self.done.emit(0, 0)
            return

        verified_count = 0

        for i, row in enumerate(unverified, start=1):
            if self._cancel.is_set():
                break

            # Abort if the user switched profiles mid-verification.
            if self._db.current_profile != self._expected_profile:
                logger.warning(
                    'Profile changed from \'%s\' to \'%s\' during keyword verification — aborting.',
                    self._expected_profile, self._db.current_profile,
                )
                self.aborted.emit()
                return

            self.progress.emit(i, total)
            self.progress_text.emit(f"Checking {i}/{total} videos…")

            content_id = row["content_id"]
            title = (row.get("title") or "").strip()
            description = (row.get("description") or "").strip()

            # Check title and description against all keyword patterns.
            matched = False
            for pattern in patterns:
                if pattern.search(title) or pattern.search(description):
                    matched = True
                    break

            if matched:
                # Cooperative guard: verify the profile hasn't changed.
                if self._db.current_profile != self._expected_profile:
                    logger.warning(
                        'Profile changed during keyword verification — aborting.'
                    )
                    self.aborted.emit()
                    return
                self._db.set_verified(content_id, True)
                self.video_verified.emit(content_id)
                verified_count += 1

        self.done.emit(verified_count, total)