"""On-demand AI worker for the Discover window.

``EvaluateWorker`` fires a **single** prompt (per the user's "don't use AI
too much" requirement) and communicates exclusively via signals: given a
discovered creator, it sends everything we have to the AI and asks whether
they're worth reaching out to, and why.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from .ai_client import call_ai, load_ai_api_key, provider_name
from .db_manager import DatabaseManager

logger = logging.getLogger(__name__)

# Ask for a compact JSON object so we can parse the verdict cleanly.
_EVAL_SYSTEM = (
    "You are a talent scout for an online content community. The community "
    "describes itself as follows:\n\n\"{community_description}\"\n\n"
    "You are given everything Kleos knows about a YouTube creator. Decide "
    "whether this creator is worth reaching out to for recruitment into the "
    "community.\n\n"
    "Respond with ONLY a compact JSON object, no markdown, no commentary, in "
    "this exact shape:\n"
    "{{\"worth_it\": true|false, \"reason\": \"one or two sentences explaining why\"}}\n"
)


class EvaluateWorker(QThread):
    """Single-prompt AI evaluation of one discovered creator.

    Signals
    -------
    done(str, str, str)
        (verdict_text, rationale, raw_response) — verdict_text is a
        human label like "Worth reaching out" / "Not worth it".
    error(str)
    api_key_missing(str)
    aborted()
    """

    done = pyqtSignal(str, str, str)
    error = pyqtSignal(str)
    api_key_missing = pyqtSignal(str)
    aborted = pyqtSignal()

    def __init__(self, db: DatabaseManager, channel_id: str, model: str, parent: Any | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._channel_id = channel_id
        self._model = model
        self._cancel = threading.Event()
        self._expected_profile = ''

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        api_key, err = load_ai_api_key(self._db, self._model)
        if err:
            self.api_key_missing.emit(err)
            return
        self._expected_profile = self._db.current_profile

        d = self._db.get_discovered_creator(self._channel_id)
        if not d:
            self.error.emit('Creator not found in discovered set.')
            return
        community_description = (self._db.get_setting('community_description') or '').strip() or '(no community description set)'

        system_prompt = _EVAL_SYSTEM.format(
            community_description=community_description.replace('{', '{{').replace('}', '}}')
        )
        titles = d.get('recent_titles') or []
        user_message = (
            f"Channel: {d.get('title', '')} ({d.get('handle', '') or d.get('channel_id', '')})\n"
            f"Subscribers: {d.get('subscriber_count', 0):,}\n"
            f"Total views: {d.get('view_count', 0):,}\n"
            f"Videos: {d.get('video_count', 0):,}\n"
            f"Upload cadence: {d.get('cadence_per_week', 0):.1f} per week\n"
            f"Views per subscriber: {d.get('views_per_sub', 0):.1f}\n"
            f"Potential score: {d.get('potential_score', 0)}/100\n"
            f"Recent titles:\n- " + '\n- '.join(titles[:5] or ['(none)'])
        )

        text, ai_err = call_ai(
            model=self._model, system_prompt=system_prompt, user_message=user_message,
            api_key=api_key, max_tokens=400, cancel_check=self._cancel.is_set,
        )
        if self._cancel.is_set():
            return
        if ai_err:
            self.error.emit(ai_err)
            return
        if self._db.current_profile != self._expected_profile:
            self.aborted.emit()
            return

        verdict_label, rationale = _parse_eval_response(text or '')
        self._db.save_ai_evaluation(
            self._channel_id, provider_name(self._model), self._model,
            verdict_label, rationale,
        )
        self.done.emit(verdict_label, rationale, text or '')


def _parse_eval_response(text: str) -> tuple[str, str]:
    """Parse the AI's evaluate JSON.  Falls back to plain text parsing.

    Returns ``(verdict_label, rationale)``.
    """
    worth_it: bool | None = None
    rationale = ''
    # Try JSON first (the prompt asks for it).
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            worth_it = bool(obj.get('worth_it'))
            rationale = str(obj.get('reason', '')).strip()
        except (json.JSONDecodeError, AttributeError):
            pass
    if worth_it is None:
        # Fallback to leading-word heuristics only — anchored on a word
        # boundary so prose like "not truly a fit", "nothing here", or
        # "nowhere notable" doesn't get misread as "no". Bare 'true'/'false'
        # substring checks are deliberately avoided (they match "truly" /
        # "not true" and invert the verdict).
        low = text.lower().strip()
        if re.match(r'yes\b', low) or '"worth_it": true' in low:
            worth_it = True
        elif re.match(r'no\b', low) or '"worth_it": false' in low:
            worth_it = False
    if not rationale:
        rationale = text.strip()
    verdict_label = 'Worth reaching out' if worth_it else ('Not worth it' if worth_it is False else 'Unsure')
    return verdict_label, rationale