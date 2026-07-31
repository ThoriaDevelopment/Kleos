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

from .ai_client import call_ai, is_local_model, load_ai_api_key, provider_name
from .db_manager import DatabaseManager

logger = logging.getLogger(__name__)

# Evaluate prompt, tuned for capable models (Claude, Gemini, 8B+ local). It
# spells out what each metric means and how to weigh them, so the model judges
# from the underlying signals and the real titles rather than parroting the
# 0-100 score. Output is reasoning first, then YES/NO alone on the final line,
# which ``_parse_eval_response`` reads cleanly (standalone verdict line).
#
# Note: a very small local model can't do this task — it echoes the prompt or
# rubber-stamps YES regardless of fit. That's a model-capability ceiling, not a
# prompt bug; see the memory note "local-llm-too-small-for-ai-tasks". The
# parser fails honestly in that case rather than showing template text.
_EVAL_SYSTEM = (
    "You are a talent scout evaluating YouTube creators for recruitment into "
    "an online content community.\n\n"
    "The community describes itself as:\n\"{community_description}\"\n\n"
    "You will be given the statistics Kleos gathered about a creator plus a "
    "few of their recent video titles. Decide whether this creator is worth "
    "reaching out to, and explain why.\n\n"
    "How to read the numbers:\n"
    "- Subscribers / Total views / Videos: the channel's raw scale.\n"
    "- Upload cadence (per week): uploads over the last 90 days. Around 1 or "
    "more per week means active and consistent; near 0 means the channel is "
    "dormant or dead, which is a strong negative even if other stats look good.\n"
    "- Views per subscriber = total views divided by subscribers. High "
    "(roughly 10 or more) means the channel reaches well beyond its own "
    "subscribers (broad or viral appeal, or a strong back catalogue) and is "
    "Kleos's strongest positive signal. Very low (under about 5) with a large "
    "subscriber count often means the audience is inactive or the channel is "
    "declining.\n"
    "- Potential score (0-100): Kleos's composite of these signals. Use it as "
    "a summary, but judge from the underlying numbers and the titles, not the "
    "score alone.\n\n"
    "How to judge:\n"
    "- Content fit matters most. Do the recent titles and topics actually "
    "match the community's focus and values? A smaller, on-topic, active "
    "creator is usually a better recruit than a large, off-topic one. Reject "
    "creators whose content clearly conflicts with the community.\n"
    "- Activity: prefer creators who upload regularly. Be sceptical of dormant "
    "channels regardless of past stats.\n"
    "- Engagement and reach: weigh views-per-subscriber and absolute reach "
    "against the community's goals — a healthy, growing audience is what makes "
    "recruiting worthwhile.\n\n"
    "Reply with your reasoning first — two to four sentences that reference "
    "this specific creator's content, cadence, and engagement and explain how "
    "they do or don't fit the community — then put the single word YES (worth "
    "reaching out) or NO (not worth it) alone on the final line.\n"
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
        # Local (Ollama) models need no API key — skip the load so the
        # removed "local" sentinel in load_ai_api_key doesn't bite.
        if is_local_model(self._model):
            api_key = ""
        else:
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
            api_key=api_key, max_tokens=1024, cancel_check=self._cancel.is_set,
            db=self._db,
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
    """Parse the AI's evaluate response into ``(verdict_label, rationale)``.

    The prompt asks for a natural answer ending in ``YES``/``NO``, but models
    emit several shapes, so this accepts (in priority order): a JSON object,
    a standalone verdict line, a leading verdict word with the reason after
    it, a trailing verdict word at the end of the last sentence, and finally
    a leading-word heuristic.  The model's own text is never discarded — if a
    real explanation exists it is shown verbatim; if the model produced none,
    a clear message is shown instead of echoing the verdict word.
    """
    raw = (text or '').strip()
    worth_it: bool | None = None
    rationale = ''

    # 1) JSON object (some models emit it regardless of the prompt).
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            w = obj.get('worth_it')
            if isinstance(w, bool):
                worth_it = w
            elif isinstance(w, str):
                worth_it = w.strip().lower() in ('true', 'yes', '1')
            reason = obj.get('reason')
            if isinstance(reason, str) and reason.strip():
                rationale = reason.strip()
        except (json.JSONDecodeError, AttributeError):
            pass

    # 2) Locate the verdict word and treat everything else as the explanation.
    if worth_it is None:
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        verdict_found = False

        # 2a) A line that is just the verdict word (anywhere in the response),
        # optionally behind a label like "Verdict:" / "Decision:" that a
        # capable model may add despite being asked for the bare word.
        for i, ln in enumerate(lines):
            vm = re.fullmatch(
                r'(?:verdict|decision|answer|recommendation|outcome)?\s*[:\-]?\s*(yes|no)[\s:.,\-]*',
                ln, re.IGNORECASE,
            )
            if vm:
                worth_it = vm.group(1).lower() == 'yes'
                lines[i] = ''
                verdict_found = True
                break

        # 2b) A line starting with the verdict word, reason after it
        # ("YES: great fit ...").
        if not verdict_found:
            for i, ln in enumerate(lines):
                vm = re.match(r'(yes|no)\b[\s:.,\-]+(.+)', ln, re.IGNORECASE)
                if vm:
                    worth_it = vm.group(1).lower() == 'yes'
                    lines[i] = vm.group(2).strip()
                    verdict_found = True
                    break

        # 2c) Trailing verdict word at the end of the last line
        # ("Great fit for the community. YES.") — the common shape for a
        # natural one-line answer.
        if not verdict_found and lines:
            vm = re.search(r'\b(yes|no)\b[\s.!?]*$', lines[-1], re.IGNORECASE)
            if vm:
                worth_it = vm.group(1).lower() == 'yes'
                lines[-1] = lines[-1][:vm.start()].strip()
                verdict_found = True

        if verdict_found:
            rationale = '\n'.join(ln for ln in lines if ln).strip()

    # 3) Last-resort leading-word heuristics — anchored on a word boundary so
    # prose like "not truly a fit", "nothing here", or "nowhere notable" isn't
    # misread as "no". Bare 'true'/'false' substring checks are deliberately
    # avoided (they match "truly" / "not true" and invert the verdict).
    if worth_it is None:
        low = raw.lower()
        if re.match(r'yes\b', low) or '"worth_it": true' in low:
            worth_it = True
        elif re.match(r'no\b', low) or '"worth_it": false' in low:
            worth_it = False

    # If the model produced no real explanation — empty, or nothing but the
    # verdict word — say so explicitly instead of echoing the verdict back as
    # the "reasoning" (which is what previously showed "Verdict: Worth
    # reaching out\n\nYES"). If there is other prose, never discard it.
    if not rationale or rationale.lower() in ('yes', 'no'):
        if worth_it is None and raw:
            rationale = raw
        else:
            rationale = '(The model did not provide an explanation.)'

    verdict_label = ('Worth reaching out' if worth_it
                     else ('Not worth it' if worth_it is False else 'Unsure'))
    return verdict_label, rationale