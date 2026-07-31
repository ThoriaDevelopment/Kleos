"""Discover & Recruit window — market research for small, high-potential
YouTube creators outside the tracked roster.

Option A placement: a standalone dialog launched from the main window
toolbar (mirroring AnalyticsWindow).  Search modes, filter panel, a
card/table results toggle, per-card Evaluate (AI) / Flag / Add-to-roster
actions.
"""
from __future__ import annotations

import logging
from typing import Any

from PyQt6 import sip
from PyQt6.QtCore import Qt, QThread, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QScrollArea, QSpinBox,
    QStackedWidget, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.db_manager import DatabaseManager
from core.discover_ai_worker import EvaluateWorker
from core.discover_worker import DiscoverWorker, VideoSearchWorker
from core.local_llm import get_ollama_host, ListLocalModelsWorker
from ui.verify_dialog import _PROVIDERS as _VERIFY_PROVIDERS  # reuse the model list
from ui.video_search_stats import VideoSearchStatsDialog
from ui.candidate_pool import CandidatePoolDialog
from ui.app_icon import create_app_icon
from ui.dialog_utils import dark_info, dark_warning, enable_window_maximize, handle_fullscreen_keypress
from ui.dialog_utils import compact_count as _fmt_count
from ui.geometry import restore_geometry, save_geometry
from ui.theme.stylesheet import build_dialog_qss
from ui.theme.tokens import C, M

logger = logging.getLogger(__name__)

# Small curated YouTube category list (ID → label) — the /search
# videoCategoryId parameter accepts these.
_YT_CATEGORIES = [
    ('', 'Any category'), ('20', 'Gaming'), ('10', 'Music'), ('27', 'Education'),
    ('28', 'Science & Tech'), ('24', 'Entertainment'), ('23', 'Comedy'),
    ('22', 'People & Blogs'), ('26', 'Howto & Style'), ('17', 'Sports'),
    ('15', 'Pets & Animals'), ('1', 'Film & Animation'),
]

_REGIONS = [
    ('', 'Worldwide'), ('US', 'United States'), ('GB', 'United Kingdom'),
    ('CA', 'Canada'), ('AU', 'Australia'), ('DE', 'Germany'), ('FR', 'France'),
    ('BR', 'Brazil'), ('JP', 'Japan'), ('KR', 'South Korea'), ('IN', 'India'),
]

_LANGUAGES = [
    ('', 'Any'), ('en', 'English'), ('es', 'Spanish'), ('pt', 'Portuguese'),
    ('de', 'German'), ('fr', 'French'), ('ja', 'Japanese'), ('ko', 'Korean'),
]

_SORTS = [
    ('potential', 'Potential score'), ('views_per_sub', 'Views per sub'),
    ('subscribers', 'Smallest first'), ('views', 'Total views'),
    ('cadence', 'Upload cadence'),
]

_SHORTS_MODES = [('always', 'Include shorts'), ('never', 'Exclude shorts')]

# Video-search timeframes — narrow the /search via ``published_after`` (already
# part of the cache key, so each window is cached independently).  The code is
# the ``timeframe`` value stored in params; the UI label is user-facing.
_TIMEFRAMES = [
    ('all', 'Any time'), ('day', 'Last day'), ('week', 'Last week'),
    ('month', 'Last month'), ('year', 'Last year'),
]

# Client-side video result sorts (computed from fetched stats — 0 extra quota).
_VIDEO_SORTS = [
    ('views', 'Views'), ('upload_date', 'Upload date'),
    ('engagement', 'Engagement'), ('title', 'Title'),
]


def _all_ai_models() -> list[tuple[str, str]]:
    """Flatten the verify-dialog cloud provider model list to (id, label) pairs.

    Local (Ollama) models are NOT included here — they are appended
    asynchronously by the Evaluate dialog so opening it never blocks on a
    network round-trip to Ollama.
    """
    out: list[tuple[str, str]] = []
    for prov in _VERIFY_PROVIDERS.values():
        for mid, label, _desc in prov['models']:
            out.append((mid, f'{prov["label"]} {label}'))
    return out


def _populate_model_combo(combo: QComboBox, db: DatabaseManager) -> None:
    """Fill an AI-model combo with the cloud models and select the saved one.

    Local models are appended later by :meth:`EvaluateDialog._load_local_models_async`.

    Reads the Discover-specific ``discover_ai_model`` setting first, then
    falls back to the Verify tab's ``auto_verify_model`` so a user who has
    only configured Verify gets a sensible default here without re-picking.
    """
    for model_id, label in _all_ai_models():
        combo.addItem(label, model_id)
    saved = db.get_setting('discover_ai_model') or db.get_setting('auto_verify_model')
    if saved:
        for i in range(combo.count()):
            if combo.itemData(i) == saved:
                combo.setCurrentIndex(i)
                break


def _fmt_ratio(r: float) -> str:
    return f'{r:.1f}'


# Holds references to QThreads that have been cancelled/retired so they are
# not garbage-collected (and thus destroyed by Qt) while still running.  Each
# worker removes itself on ``finished`` and schedules its own deletion.
_RETIRING_WORKERS: set = set()


def _retire_worker(worker: QThread) -> None:
    """Disconnect a worker's GUI-mutating signals and let it finish and
    self-delete instead of being destroyed mid-run.

    Used when cancelling an in-flight search (e.g. the user starts a new one
    or closes the window): the underlying HTTP requests can't be interrupted
    instantly, so we drop our interest in the result and let the thread wind
    down quietly.
    """
    for name in ('progress', 'results_ready', 'error', 'api_key_missing',
                 'aborted', 'done', 'not_found', 'finished'):
        sig = getattr(worker, name, None)
        if sig is None:
            continue
        try:
            sig.disconnect()
        except (TypeError, RuntimeError):
            pass
    _RETIRING_WORKERS.add(worker)
    worker.finished.connect(lambda *_: (_RETIRING_WORKERS.discard(worker), worker.deleteLater()))


class _DiscoverCard(QFrame):
    """A single discovered-creator result card."""

    def __init__(self, data: dict[str, Any], window: 'DiscoverWindow') -> None:
        super().__init__()
        self._data = data
        self._window = window
        self.setObjectName('card')
        self.setFrameShape(QFrame.Shape.Box)
        self.setMinimumWidth(230)
        self.setMaximumWidth(260)
        # The whole card is clickable to open the creator's YouTube channel;
        # the action buttons below consume their own clicks, so they still
        # work independently.
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('Click to open this creator on YouTube')

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(12, 10, 12, 10)
        vbox.setSpacing(6)

        # Header: avatar initial + title + handle.
        header = QHBoxLayout()
        avatar = QLabel(data.get('title', '?')[:1].upper() if data.get('title') else '?')
        avatar.setFixedSize(36, 36)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            f'background: {C.AVATAR_BG}; color: {C.AVATAR_FG}; border-radius: 18px;'
            f' font-weight: bold; font-size: 16px;'
        )
        header.addWidget(avatar)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel(data.get('title', '(unknown)'))
        title.setObjectName('cardName')
        title.setWordWrap(True)
        title_box.addWidget(title)
        handle = QLabel(data.get('handle') or data.get('channel_id', ''))
        handle.setObjectName('cardSubs')
        title_box.addWidget(handle)
        header.addLayout(title_box, 1)
        vbox.addLayout(header)

        # Stats row.
        subs = data.get('subscriber_count', 0)
        views = data.get('view_count', 0)
        vps = data.get('views_per_sub', 0)
        stats = QLabel(
            f'{_fmt_count(subs)} subs · {_fmt_count(views)} views · '
            f'{_fmt_ratio(vps)} views/sub'
        )
        stats.setObjectName('cardSubs')
        stats.setWordWrap(True)
        vbox.addWidget(stats)

        cadence = data.get('cadence_per_week', 0)
        meta = QLabel(f'↑ {cadence:.1f}/wk · {_fmt_ratio(data.get("growth_signal", 0))}× growth')
        meta.setObjectName('cardMeta')
        vbox.addWidget(meta)

        # Potential bar.
        score = int(data.get('potential_score', 0))
        pot_row = QHBoxLayout()
        pot_label = QLabel(f'Potential {score}')
        pot_label.setObjectName('accentLabel')
        pot_row.addWidget(pot_label)
        pot_row.addStretch(1)
        bar = QLabel()
        bar.setFixedHeight(8)
        bar.setMinimumWidth(120)
        # A crude inline bar via background gradient width from the score.
        bar.setStyleSheet(
            f'background: qlineargradient(x1:0,y1:0,x2:1,y2:0,'
            f'stop:0 {C.ACCENT}, stop:{max(0.02, score/100.0)} {C.ACCENT}, '
            f'stop:{max(0.03, score/100.0 + 0.01)} {C.BG_LAYER}, stop:1 {C.BG_LAYER});'
            f' border-radius: 4px;'
        )
        pot_row.addWidget(bar, 1)
        vbox.addLayout(pot_row)

        # Recent titles preview.
        titles = data.get('recent_titles') or []
        if titles:
            preview = QLabel('• ' + '\n• '.join(titles[:3]))
            preview.setObjectName('cardSubs')
            preview.setWordWrap(True)
            vbox.addWidget(preview)

        # Optional AI suggestion note attached to a discovered creator
        # (the AI's per-channel reason).  Not persisted, so it only shows
        # for the session that produced it.
        note = data.get('ai_note')
        if note:
            note_lbl = QLabel(f'AI: {note}')
            note_lbl.setObjectName('cardMeta')
            note_lbl.setWordWrap(True)
            vbox.addWidget(note_lbl)

        # Actions.
        actions = QHBoxLayout()
        add_btn = QPushButton('+ Add')
        add_btn.setToolTip('Add this creator to the tracked roster')
        add_btn.clicked.connect(self._on_add)
        actions.addWidget(add_btn)
        eval_btn = QPushButton('Eval')
        eval_btn.setToolTip('Ask the AI whether this creator is worth reaching out to (1 prompt)')
        eval_btn.clicked.connect(self._on_eval)
        actions.addWidget(eval_btn)
        self._flag_btn = QPushButton('⚑ Flag' if not data.get('is_flagged') else '✓ Flagged')
        self._flag_btn.setToolTip('Add to the flagged candidate pool for outreach')
        self._flag_btn.clicked.connect(self._on_flag)
        actions.addWidget(self._flag_btn)
        vbox.addLayout(actions)

    def _on_add(self) -> None:
        self._window.promote_to_roster(self._data)

    def _on_eval(self) -> None:
        self._window.evaluate_creator(self._data)

    def _on_flag(self) -> None:
        self._window.toggle_flag(self._data, self._flag_btn)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # Left-click anywhere on the card (background or labels — buttons
        # accept their own press and never reach here) opens the creator's
        # YouTube channel page in the system's default browser.
        if event.button() == Qt.MouseButton.LeftButton:
            self._window.open_channel_page(self._data.get('channel_id', ''))
        super().mousePressEvent(event)


class DiscoverWindow(QDialog):
    """Discover & Recruit window (Option A — standalone dialog)."""

    def __init__(self, db: DatabaseManager, parent: QWidget | None = None, *, on_roster_changed=None, on_pool_changed=None) -> None:
        super().__init__(parent)
        enable_window_maximize(self)
        self._db = db
        self._on_roster_changed = on_roster_changed
        self._on_pool_changed = on_pool_changed
        self._results: list[dict[str, Any]] = []
        self._worker: QThread | None = None
        # Monotonic id stamped on each search so a queued results_ready from a
        # cancelled/superseded worker can be ignored instead of overwriting
        # fresh results.
        self._search_id = 0
        self.setWindowTitle('Discover & Recruit')
        self.setWindowIcon(create_app_icon())
        self.setMinimumSize(900, 640)
        self.resize(1100, 760)
        self.reapply_theme()
        restore_geometry(self, 'DiscoverWindow', self._db)
        self.finished.connect(lambda _r: save_geometry(self, 'DiscoverWindow', self._db))
        self._build_ui()
        # Surface creators discovered in prior sessions so the user doesn't
        # have to spend quota re-searching to see their last result set.
        self._results = self._db.get_discovered_creators(
            sort=self._sort_combo.currentData() or 'potential',
        )
        if self._results:
            self._render_results()
            n = len(self._results)
            self._status.setText(
                f'{n} previously discovered creator{"s" if n != 1 else ""}. '
                f'Run a new search to refresh.'
            )
        self._refresh_candidates_badge()

    # ── theme / lifecycle ─────────────────────────────────────────────

    def reapply_theme(self) -> None:
        self.setStyleSheet(build_dialog_qss())

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if handle_fullscreen_keypress(self, event):
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._cancel_worker()
        self._v_cancel_worker()
        super().closeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # The first _render_results ran during __init__ before the dialog was
        # laid out, so the cards grid used a stale viewport width.  Reflow on
        # the next tick once the real width is known.
        if hasattr(self, '_reflow_timer'):
            self._reflow_timer.start()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # Debounced reflow so the grid re-columns as the window is resized.
        if hasattr(self, '_reflow_timer'):
            self._reflow_timer.start()

    # ── UI construction ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(14, 14, 14, 14)
        vbox.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel('Discover & Recruit')
        title.setObjectName('dialogTitle')
        header.addWidget(title)
        header.addStretch(1)
        self._candidates_btn = QPushButton('⚑ Candidates')
        self._candidates_btn.setToolTip('Flagged creators from Discover with outreach notes')
        self._candidates_btn.clicked.connect(self._on_open_candidates)
        header.addWidget(self._candidates_btn)
        vbox.addLayout(header)
        hint = QLabel('Search YouTube for small, high-potential creators in a niche.')
        hint.setObjectName('hintLabel')
        vbox.addWidget(hint)

        # Channels and Videos live as parallel tabs so the channel-search
        # behavior is unchanged while video search / media coverage / the
        # stats panel get their own surface.
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_channels_tab(), 'Channels')
        self._tabs.addTab(self._build_videos_tab(), 'Videos')
        vbox.addWidget(self._tabs, 1)

    def _build_channels_tab(self) -> QWidget:
        """The existing channel search surface, now wrapped in a tab page.

        All channel widgets (``self._kw_edit`` … ``self._results_stack``) are
        created here exactly as they were when inlined in ``_build_ui``, so the
        existing search / card / table / candidate logic is untouched.
        """
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(10)

        # One search type — all inputs visible at once across two rows:
        # row 1: keywords / region / language,  row 2: category / seed channels.
        v.addLayout(self._build_inputs_row_1())
        v.addLayout(self._build_inputs_row_2())
        v.addLayout(self._build_filter_row())
        v.addLayout(self._build_action_row())
        v.addWidget(self._build_progress_widget())
        v.addLayout(self._build_results_toggle_row())

        # Debounced re-layout of the cards grid so it reflows to the real
        # viewport width on first show (and on window resize) instead of
        # staying stuck at the pre-layout column count.
        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.setInterval(120)
        self._reflow_timer.timeout.connect(self._reflow_cards)

        self._results_stack = QStackedWidget()
        self._cards_scroll = QScrollArea()
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.viewport().setStyleSheet('background: transparent;')
        self._cards_container = QWidget()
        self._cards_container.setStyleSheet('background: transparent;')
        self._cards_grid = QGridLayout(self._cards_container)
        self._cards_grid.setSpacing(10)
        self._cards_grid.setContentsMargins(2, 2, 2, 2)
        self._cards_scroll.setWidget(self._cards_container)
        self._results_stack.addWidget(self._cards_scroll)
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(['Creator', 'Subs', 'Views', 'Views/sub', 'Cadence/wk', 'Potential', 'Actions'])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.cellDoubleClicked.connect(self._on_table_row_double_clicked)
        self._results_stack.addWidget(self._table)
        v.addWidget(self._results_stack, 1)

        self._status = QLabel('No results yet. Run a search to find creators.')
        self._status.setObjectName('countLabel')
        v.addWidget(self._status)
        return page

    def _build_videos_tab(self) -> QWidget:
        """Parallel video-search surface.

        Reuses the same filter knobs as the Channels tab (prefixed ``_v_`` so
        they don't shadow the channel widgets) plus a Timeframe combo that
        narrows the search via ``published_after``.  Results render in a table
        with per-row Open / Add-channel actions and a 📊 Stats button that opens
        the 0-quota charts panel.
        """
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(10)

        # Row 1: keywords / region / language (mirrors the channel row 1).
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self._v_kw_edit = QLineEdit()
        self._v_kw_edit.setPlaceholderText('Keywords, e.g. "minecraft SMP server"')
        self._prefilled_kw = (self._db.get_setting('verify_keywords') or '').strip()
        self._v_kw_edit.setText(self._prefilled_kw)
        self._v_kw_edit.setMinimumWidth(260)
        row1.addWidget(QLabel('Keywords:'))
        row1.addWidget(self._v_kw_edit, 1)
        self._v_region_combo = QComboBox()
        for code, label in _REGIONS:
            self._v_region_combo.addItem(label, code)
        row1.addWidget(QLabel('Region:'))
        row1.addWidget(self._v_region_combo)
        self._v_lang_combo = QComboBox()
        for code, label in _LANGUAGES:
            self._v_lang_combo.addItem(label, code)
        row1.addWidget(QLabel('Language:'))
        row1.addWidget(self._v_lang_combo)
        v.addLayout(row1)

        # Row 2: category / timeframe (timeframe replaces the Channels tab's
        # seed-channels box — seeds are a channel-discovery aid, irrelevant to
        # a video search).
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self._v_category_combo = QComboBox()
        for cid, label in _YT_CATEGORIES:
            self._v_category_combo.addItem(label, cid)
        row2.addWidget(QLabel('Category:'))
        row2.addWidget(self._v_category_combo)
        self._v_timeframe_combo = QComboBox()
        for code, label in _TIMEFRAMES:
            self._v_timeframe_combo.addItem(label, code)
        row2.addWidget(QLabel('Timeframe:'))
        row2.addWidget(self._v_timeframe_combo)
        row2.addStretch(1)
        v.addLayout(row2)

        # Filter row: sub ceiling / min subs / shorts / max results.
        frow = QHBoxLayout()
        frow.setSpacing(8)
        frow.addWidget(QLabel('Sub ceiling:'))
        self._v_sub_ceiling = QSpinBox()
        self._v_sub_ceiling.setRange(0, 10_000_000)
        self._v_sub_ceiling.setValue(int(self._db.get_setting('discover_sub_ceiling') or 0))
        self._v_sub_ceiling.setToolTip('0 = no ceiling (show all sizes)')
        frow.addWidget(self._v_sub_ceiling)
        frow.addWidget(QLabel('Min subs:'))
        self._v_min_subs = QSpinBox()
        self._v_min_subs.setRange(0, 10_000_000)
        self._v_min_subs.setValue(int(self._db.get_setting('discover_min_subscribers') or 0))
        self._v_min_subs.setToolTip('0 = no minimum (show all sizes)')
        frow.addWidget(self._v_min_subs)
        frow.addWidget(QLabel('Shorts:'))
        self._v_shorts_combo = QComboBox()
        for val, label in _SHORTS_MODES:
            self._v_shorts_combo.addItem(label, val)
        frow.addWidget(self._v_shorts_combo)
        frow.addWidget(QLabel('Max results:'))
        self._v_max_results = QSpinBox()
        self._v_max_results.setRange(10, 200)
        self._v_max_results.setSingleStep(10)
        self._v_max_results.setValue(100)
        frow.addWidget(self._v_max_results)
        frow.addStretch(1)
        v.addLayout(frow)

        # Action row: Run Search + Media Coverage + cache label.
        arow = QHBoxLayout()
        self._v_run_btn = QPushButton('🔍 Run Search')
        self._v_run_btn.setObjectName('accentPrimary')
        self._v_run_btn.setToolTip('Search YouTube for videos matching the filters (≈100–200 quota units; cached)')
        self._v_run_btn.clicked.connect(self._v_on_run_search)
        arow.addWidget(self._v_run_btn)
        self._v_coverage_btn = QPushButton('★ Media Coverage')
        self._v_coverage_btn.setToolTip('Search for videos that mention your community (uses the Community Name from Settings)')
        self._v_coverage_btn.clicked.connect(self._v_on_media_coverage)
        arow.addWidget(self._v_coverage_btn)
        arow.addStretch(1)
        self._v_cache_label = QLabel()
        self._v_cache_label.setObjectName('countLabel')
        arow.addWidget(self._v_cache_label)
        self._v_refresh_cache_label()
        v.addLayout(arow)

        # Progress row (mirrors the Channels tab's progress widget).
        self._v_progress_widget = QWidget()
        ph = QHBoxLayout(self._v_progress_widget)
        ph.setContentsMargins(0, 0, 0, 0)
        self._v_progress_label = QLabel('')
        self._v_progress_label.setObjectName('countLabel')
        ph.addWidget(self._v_progress_label, 1)
        self._v_cancel_btn = QPushButton('Cancel')
        self._v_cancel_btn.clicked.connect(self._v_cancel_worker)
        self._v_cancel_btn.setVisible(False)
        ph.addWidget(self._v_cancel_btn)
        self._v_progress_widget.setVisible(False)
        v.addWidget(self._v_progress_widget)

        # Results header: sort combo + Stats button.
        rrow = QHBoxLayout()
        rrow.addWidget(QLabel('Sort:'))
        self._v_sort_combo = QComboBox()
        for val, label in _VIDEO_SORTS:
            self._v_sort_combo.addItem(label, val)
        self._v_sort_combo.currentIndexChanged.connect(self._v_render_table)
        rrow.addWidget(self._v_sort_combo)
        rrow.addStretch(1)
        self._v_stats_btn = QPushButton('📊 Stats')
        self._v_stats_btn.setToolTip('Open the stats panel for the current results (2 charts, 0 extra quota)')
        self._v_stats_btn.setEnabled(False)
        self._v_stats_btn.clicked.connect(self._v_open_stats)
        rrow.addWidget(self._v_stats_btn)
        v.addLayout(rrow)

        # Results table.
        self._v_table = QTableWidget(0, 9)
        self._v_table.setHorizontalHeaderLabels(
            ['Title', 'Channel', 'Subs', 'Views', 'Likes', 'Comments', 'Uploaded', 'Type', 'Actions']
        )
        self._v_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._v_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._v_table.horizontalHeader().setStretchLastSection(False)
        self._v_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._v_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._v_table.cellDoubleClicked.connect(self._v_on_table_double_clicked)
        v.addWidget(self._v_table, 1)

        self._v_status = QLabel('No results yet. Run a search to find videos.')
        self._v_status.setObjectName('countLabel')
        v.addWidget(self._v_status)

        self._v_results: list[dict[str, Any]] = []
        self._v_worker: QThread | None = None
        # Monotonic id for the video search (see self._search_id).
        self._v_search_id = 0
        return page

    def _build_inputs_row_1(self) -> QHBoxLayout:
        """Row 1: keywords, region, language."""
        row = QHBoxLayout()
        row.setSpacing(8)

        self._kw_edit = QLineEdit()
        self._kw_edit.setPlaceholderText('Keywords, e.g. "minecraft SMP server"')
        self._prefilled_kw = (self._db.get_setting('verify_keywords') or '').strip()
        self._kw_edit.setText(self._prefilled_kw)
        self._kw_edit.setMinimumWidth(260)
        row.addWidget(QLabel('Keywords:'))
        row.addWidget(self._kw_edit, 1)

        self._region_combo = QComboBox()
        for code, label in _REGIONS:
            self._region_combo.addItem(label, code)
        row.addWidget(QLabel('Region:'))
        row.addWidget(self._region_combo)

        self._lang_combo = QComboBox()
        for code, label in _LANGUAGES:
            self._lang_combo.addItem(label, code)
        row.addWidget(QLabel('Language:'))
        row.addWidget(self._lang_combo)
        return row

    def _build_inputs_row_2(self) -> QHBoxLayout:
        """Row 2: category, seed channels."""
        row = QHBoxLayout()
        row.setSpacing(8)

        self._category_combo = QComboBox()
        for cid, label in _YT_CATEGORIES:
            self._category_combo.addItem(label, cid)
        row.addWidget(QLabel('Category:'))
        row.addWidget(self._category_combo)

        self._seed_edit = QLineEdit()
        self._seed_edit.setPlaceholderText('@handle or channel ID, comma-separated')
        self._seed_edit.setMinimumWidth(220)
        row.addWidget(QLabel('Seed channels:'))
        row.addWidget(self._seed_edit, 1)
        return row

    def _build_filter_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel('Sub ceiling:'))
        self._sub_ceiling = QSpinBox()
        self._sub_ceiling.setRange(0, 10_000_000)
        self._sub_ceiling.setValue(int(self._db.get_setting('discover_sub_ceiling') or 0))
        self._sub_ceiling.setToolTip('0 = no ceiling (show all sizes)')
        row.addWidget(self._sub_ceiling)
        row.addWidget(QLabel('Min subs:'))
        self._min_subs = QSpinBox()
        self._min_subs.setRange(0, 10_000_000)
        self._min_subs.setValue(int(self._db.get_setting('discover_min_subscribers') or 0))
        self._min_subs.setToolTip('0 = no minimum (show all sizes)')
        row.addWidget(self._min_subs)
        row.addWidget(QLabel('Min views/sub:'))
        self._min_vps = QSpinBox()
        self._min_vps.setRange(0, 10000)
        self._min_vps.setValue(int(self._db.get_setting('discover_min_views_per_sub') or 10))
        row.addWidget(self._min_vps)
        row.addWidget(QLabel('Shorts:'))
        self._shorts_combo = QComboBox()
        for val, label in _SHORTS_MODES:
            self._shorts_combo.addItem(label, val)
        saved_shorts = self._db.get_setting('discover_shorts') or 'always'
        if saved_shorts not in ('always', 'never'):
            saved_shorts = 'always'
        for i in range(self._shorts_combo.count()):
            if self._shorts_combo.itemData(i) == saved_shorts:
                self._shorts_combo.setCurrentIndex(i)
                break
        row.addWidget(self._shorts_combo)
        row.addWidget(QLabel('Max results:'))
        self._max_results = QSpinBox()
        self._max_results.setRange(10, 200)
        self._max_results.setSingleStep(10)
        self._max_results.setValue(100)
        row.addWidget(self._max_results)
        row.addStretch(1)

        # Keep min ≤ ceiling: 0 means "no bound", so only clamp when the
        # bound that's set is positive.  Raising the floor pulls the ceiling
        # up; lowering the ceiling pulls the floor down — neither can cross
        # the other.
        self._sub_ceiling.valueChanged.connect(self._on_ceiling_changed)
        self._min_subs.valueChanged.connect(self._on_min_subs_changed)
        return row

    def _on_ceiling_changed(self, ceiling: int) -> None:
        if ceiling > 0 and self._min_subs.value() > ceiling:
            self._min_subs.blockSignals(True)
            self._min_subs.setValue(ceiling)
            self._min_subs.blockSignals(False)

    def _on_min_subs_changed(self, minimum: int) -> None:
        ceiling = self._sub_ceiling.value()
        if ceiling > 0 and minimum > ceiling:
            self._sub_ceiling.blockSignals(True)
            self._sub_ceiling.setValue(minimum)
            self._sub_ceiling.blockSignals(False)

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._run_btn = QPushButton('🔍 Run Search')
        self._run_btn.setObjectName('accentPrimary')
        self._run_btn.setToolTip('Search YouTube and score the results (≈100–200 quota units)')
        self._run_btn.clicked.connect(self._on_run_search)
        row.addWidget(self._run_btn)
        row.addStretch(1)
        self._cache_label = QLabel()
        self._cache_label.setObjectName('countLabel')
        row.addWidget(self._cache_label)
        self._refresh_cache_label()
        return row

    def _build_progress_widget(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        self._progress_label = QLabel('')
        self._progress_label.setObjectName('countLabel')
        h.addWidget(self._progress_label, 1)
        self._cancel_btn = QPushButton('Cancel')
        self._cancel_btn.clicked.connect(self._cancel_worker)
        self._cancel_btn.setVisible(False)
        h.addWidget(self._cancel_btn)
        w.setVisible(False)
        self._progress_widget = w
        return w

    def _build_results_toggle_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel('View:'))
        self._view_cards_btn = QPushButton('Cards')
        self._view_cards_btn.setCheckable(True)
        self._view_cards_btn.setChecked(True)
        self._view_cards_btn.clicked.connect(lambda: self._results_stack.setCurrentIndex(0))
        row.addWidget(self._view_cards_btn)
        self._view_table_btn = QPushButton('Table')
        self._view_table_btn.setCheckable(True)
        self._view_table_btn.clicked.connect(lambda: self._results_stack.setCurrentIndex(1))
        row.addWidget(self._view_table_btn)
        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        self._view_group.addButton(self._view_cards_btn)
        self._view_group.addButton(self._view_table_btn)
        row.addStretch(1)
        self._sort_combo = QComboBox()
        for val, label in _SORTS:
            self._sort_combo.addItem(label, val)
        saved_sort = self._db.get_setting('discover_default_sort') or 'potential'
        for i in range(self._sort_combo.count()):
            if self._sort_combo.itemData(i) == saved_sort:
                self._sort_combo.setCurrentIndex(i)
                break
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        row.addWidget(QLabel('Sort:'))
        row.addWidget(self._sort_combo)
        return row

    # ── search ─────────────────────────────────────────────────────────

    def _on_run_search(self) -> None:
        # One search type: every field is optional and combined.  The query
        # comes from the keywords box; if that's empty but seed channels are
        # given the worker derives a query from the seeds; if both are empty
        # the community description (or a category/region-only search) is the
        # fallback.  region / language / category are always applied as
        # /search filters regardless of whether a text query is present.
        params: dict[str, Any] = {
            'sub_ceiling': self._sub_ceiling.value(),
            'min_subscribers': self._min_subs.value(),
            'min_views_per_sub': self._min_vps.value(),
            'shorts_mode': self._shorts_combo.currentData(),
            'max_results': self._max_results.value(),
            'region_code': self._region_combo.currentData() or None,
            'relevance_language': self._lang_combo.currentData() or None,
            'video_category_id': self._category_combo.currentData() or None,
        }
        query = self._kw_edit.text().strip()
        # Only send an explicit query when the user has edited the box away
        # from the prefilled community keywords; an unedited prefill behaves
        # as an empty box so the search falls back to the community keywords
        # exactly as before the prefill (preserving the worker's short-token
        # filter and the cached-result key).
        if query and query != self._prefilled_kw:
            params['query'] = query
        seeds = [s.strip() for s in self._seed_edit.text().split(',') if s.strip()]
        if seeds:
            params['seed_channels'] = seeds

        has_community_kw = bool((self._db.get_setting('verify_keywords') or '').strip()
                               or (self._db.get_setting('community_name') or '').strip())
        if (not query and not seeds and not params['video_category_id']
                and not params['region_code'] and not has_community_kw):
            dark_warning(
                self, 'Nothing to search',
                'Enter keywords, seed channels, a category or region, or set '
                'community keywords / a community name in Settings → Verify.')
            return

        self._start_worker(params)

    def _start_worker(self, params: dict[str, Any]) -> None:
        self._cancel_worker()
        self._set_running(True)
        self._run_btn.setEnabled(False)
        # Stamp this search with a fresh monotonic id; the results_ready
        # lambda checks it so a queued emit from a cancelled/superseded
        # worker can't overwrite fresh results.
        self._search_id += 1
        sid = self._search_id
        self._worker = DiscoverWorker(self._db, params)
        self._worker.progress.connect(self._on_progress)
        self._worker.results_ready.connect(lambda r, _sid=sid: self._on_results(r, _sid))
        self._worker.error.connect(self._on_error)
        self._worker.api_key_missing.connect(self._on_api_key_missing)
        self._worker.aborted.connect(self._on_aborted)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _cancel_worker(self) -> None:
        w = self._worker
        self._worker = None
        if w is None:
            return
        if w.isRunning():
            w.cancel()
            # Let the thread wind down quietly without being GC'd mid-run
            # and without its ``finished`` signal re-enabling the UI while a
            # new search is starting.
            _retire_worker(w)
            # Race guard: if the worker finished between the isRunning() check
            # above and the cleanup connect inside _retire_worker, the cleanup
            # lambda would never fire — clean up directly so it can't leak.
            if not w.isRunning():
                _RETIRING_WORKERS.discard(w)
                try:
                    w.deleteLater()
                except (RuntimeError, TypeError):
                    pass
        else:
            w.deleteLater()

    def _on_worker_finished(self) -> None:
        self._set_running(False)
        self._run_btn.setEnabled(True)

    def _set_running(self, running: bool) -> None:
        self._progress_widget.setVisible(running)
        self._cancel_btn.setVisible(running)
        if not running:
            self._progress_label.setText('')

    def _on_progress(self, msg: str) -> None:
        self._progress_label.setText(msg)

    def _on_results(self, results: list[dict[str, Any]], sid: int) -> None:
        # Ignore stale results from a cancelled or superseded search.
        if sid != self._search_id:
            return
        self._results = results
        self._render_results()
        n = len(results)
        self._status.setText(f'{n} creator{"s" if n != 1 else ""} found.' if n else 'No creators matched the filters. Try a broader query or raise the sub ceiling.')
        self._refresh_cache_label()

    def _on_error(self, msg: str) -> None:
        dark_warning(self, 'Discover error', msg)

    def _on_api_key_missing(self, msg: str) -> None:
        dark_warning(self, 'API key required', msg)

    def _on_aborted(self) -> None:
        self._status.setText('Search cancelled (profile switched).')

    def _on_sort_changed(self, _idx: int) -> None:
        self._render_results()

    # ── video search ─────────────────────────────────────────────────────

    @staticmethod
    def _timeframe_to_published_after(code: str) -> str | None:
        """Map a timeframe code to a YouTube ``publishedAfter`` ISO UTC string.

        ``published_after`` is already part of the search-cache key, so each
        timeframe window is cached independently (a repeat = 0 units).
        """
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        delta = {
            'day': timedelta(days=1),
            'week': timedelta(weeks=1),
            'month': timedelta(days=30),
            'year': timedelta(days=365),
        }.get(code)
        if delta is None:
            return None
        return (now - delta).strftime('%Y-%m-%dT%H:%M:%SZ')

    def _v_build_params(self, query: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            'result_mode': 'videos',
            'sub_ceiling': self._v_sub_ceiling.value(),
            'min_subscribers': self._v_min_subs.value(),
            'shorts_mode': self._v_shorts_combo.currentData(),
            'max_results': self._v_max_results.value(),
            'region_code': self._v_region_combo.currentData() or None,
            'relevance_language': self._v_lang_combo.currentData() or None,
            'video_category_id': self._v_category_combo.currentData() or None,
            'published_after': self._timeframe_to_published_after(
                self._v_timeframe_combo.currentData() or 'all'),
        }
        q = (query if query is not None else self._v_kw_edit.text()).strip()
        # Treat an unedited prefilled box as empty (see _on_run_search) so a
        # plain Run Search falls back to community keywords as before; an
        # explicit query arg (e.g. Media Coverage) is always honored.
        if q and (query is not None or q != self._prefilled_kw):
            params['query'] = q
        return params

    def _v_on_run_search(self) -> None:
        params = self._v_build_params()
        query = params.get('query')
        has_community_kw = bool((self._db.get_setting('verify_keywords') or '').strip()
                                or (self._db.get_setting('community_name') or '').strip())
        if (not query and not params['video_category_id']
                and not params['region_code'] and not has_community_kw):
            dark_warning(
                self, 'Nothing to search',
                'Enter keywords, a category or region, or set community keywords / '
                'a community name in Settings → Verify.')
            return
        self._v_start_worker(params)

    def _v_on_media_coverage(self) -> None:
        """Run a video search for the community's name — videos that mention it."""
        name = (self._db.get_setting('community_name') or '').strip()
        if not name:
            dark_warning(
                self, 'No community name',
                'Set a Community Name in Settings → Verify to search for media coverage.')
            return
        self._v_kw_edit.setText(name)
        self._v_start_worker(self._v_build_params(query=name))

    def _v_start_worker(self, params: dict[str, Any]) -> None:
        self._v_cancel_worker()
        self._v_set_running(True)
        self._v_run_btn.setEnabled(False)
        self._v_coverage_btn.setEnabled(False)
        # Stamp this video search with a fresh id (see _start_worker).
        self._v_search_id += 1
        sid = self._v_search_id
        self._v_worker = VideoSearchWorker(self._db, params)
        self._v_worker.progress.connect(self._v_on_progress)
        self._v_worker.results_ready.connect(lambda r, _sid=sid: self._v_on_results(r, _sid))
        self._v_worker.error.connect(self._v_on_error)
        self._v_worker.api_key_missing.connect(self._on_api_key_missing)
        self._v_worker.aborted.connect(self._v_on_aborted)
        self._v_worker.finished.connect(self._v_on_worker_finished)
        self._v_worker.start()

    def _v_cancel_worker(self) -> None:
        w = self._v_worker
        self._v_worker = None
        if w is None:
            return
        if w.isRunning():
            w.cancel()
            _retire_worker(w)
            # Race guard: see _cancel_worker.
            if not w.isRunning():
                _RETIRING_WORKERS.discard(w)
                try:
                    w.deleteLater()
                except (RuntimeError, TypeError):
                    pass
        else:
            w.deleteLater()

    def _v_on_worker_finished(self) -> None:
        self._v_set_running(False)
        self._v_run_btn.setEnabled(True)
        self._v_coverage_btn.setEnabled(True)

    def _v_set_running(self, running: bool) -> None:
        self._v_progress_widget.setVisible(running)
        self._v_cancel_btn.setVisible(running)
        if not running:
            self._v_progress_label.setText('')

    def _v_on_progress(self, msg: str) -> None:
        self._v_progress_label.setText(msg)

    def _v_on_results(self, results: list[dict[str, Any]], sid: int) -> None:
        # Ignore stale results from a cancelled or superseded video search.
        if sid != self._v_search_id:
            return
        self._v_results = results
        self._v_render_table()
        n = len(results)
        self._v_status.setText(
            f'{n} video{"s" if n != 1 else ""} found.' if n
            else 'No videos matched the filters. Try a broader query or a wider timeframe.')
        self._v_stats_btn.setEnabled(n > 0)
        self._v_refresh_cache_label()

    def _v_on_error(self, msg: str) -> None:
        dark_warning(self, 'Discover error', msg)

    def _v_on_aborted(self) -> None:
        self._v_status.setText('Search cancelled (profile switched).')

    def _v_refresh_cache_label(self) -> None:
        count = self._db.count_cached_searches()
        self._v_cache_label.setText(f'{count} cached search{"es" if count != 1 else ""}')

    def _v_render_table(self) -> None:
        sort = self._v_sort_combo.currentData() or 'views'
        items = sorted(self._v_results, key=lambda r: {
            'views': -(int(r.get('view_count', 0) or 0)),
            'upload_date': (r.get('upload_date', '') or ''),
            'engagement': -(int(r.get('like_count', 0) or 0) + int(r.get('comment_count', 0) or 0)),
            'title': (r.get('title', '') or '').lower(),
        }.get(sort, -(int(r.get('view_count', 0) or 0))))
        self._v_table.setRowCount(len(items))
        for i, v in enumerate(items):
            title_item = QTableWidgetItem(v.get('title', ''))
            title_item.setData(Qt.ItemDataRole.UserRole, v.get('video_id', ''))
            title_item.setToolTip('Double-click to open on YouTube')
            self._v_table.setItem(i, 0, title_item)
            self._v_table.setItem(i, 1, QTableWidgetItem(v.get('channel_title', '')))
            self._v_table.setItem(i, 2, QTableWidgetItem(_fmt_count(v.get('subscriber_count', 0))))
            self._v_table.setItem(i, 3, QTableWidgetItem(_fmt_count(v.get('view_count', 0))))
            self._v_table.setItem(i, 4, QTableWidgetItem(_fmt_count(v.get('like_count', 0))))
            self._v_table.setItem(i, 5, QTableWidgetItem(_fmt_count(v.get('comment_count', 0))))
            self._v_table.setItem(i, 6, QTableWidgetItem((v.get('upload_date', '') or '')[:10]))
            if v.get('is_stream'):
                vtype = 'Stream'
            elif v.get('is_short'):
                vtype = 'Short'
            else:
                vtype = 'Video'
            self._v_table.setItem(i, 7, QTableWidgetItem(vtype))
            actions = QWidget()
            ah = QHBoxLayout(actions)
            ah.setContentsMargins(2, 2, 2, 2)
            open_btn = QPushButton('Open')
            open_btn.setToolTip('Open this video on YouTube')
            open_btn.clicked.connect(lambda _, vid=v.get('video_id', ''): self._v_open_video(vid))
            add_btn = QPushButton('+ Add')
            add_btn.setToolTip('Add this video\'s channel to the tracked roster')
            add_btn.clicked.connect(lambda _, d=v: self._v_add_channel(d))
            ah.addWidget(open_btn)
            ah.addWidget(add_btn)
            ah.addStretch(1)
            self._v_table.setCellWidget(i, 8, actions)
        self._v_table.resizeColumnsToContents()
        self._v_table.setColumnWidth(0, 240)
        self._v_table.setColumnWidth(1, 160)

    def _v_open_video(self, video_id: str) -> None:
        vid = (video_id or '').strip()
        if not vid:
            return
        QDesktopServices.openUrl(QUrl(f'https://www.youtube.com/watch?v={vid}'))

    def _v_add_channel(self, data: dict[str, Any]) -> None:
        """Promote a video result's channel to the tracked roster.

        The channel isn't in the discovered set (video search doesn't upsert
        discovered creators), so upsert a minimal discovered row first so the
        existing ``promote_candidate_to_roster`` path can pick it up.
        """
        roles = self._db.get_roles()
        if not roles:
            dark_warning(self, 'No roles', 'Create at least one role in Settings before promoting a creator.')
            return
        chan = {
            'channel_id': data.get('channel_id', ''),
            'handle': data.get('handle', '') or '',
            'title': data.get('channel_title', '') or data.get('title', '') or '',
            'pfp_url': data.get('pfp_url', '') or '',
            'subscriber_count': int(data.get('subscriber_count', 0) or 0),
            'view_count': 0, 'video_count': 0, 'cadence_per_week': 0.0,
            'growth_signal': 0.0, 'engagement': 0.0, 'niche_fit': 0.0,
            'views_per_sub': 0.0, 'potential_score': 0, 'recent_titles': [],
            'is_short_channel': 1 if data.get('is_short') else 0,
            'last_refreshed_at': '',
        }
        self._db.upsert_discovered_creator(chan)
        self.promote_to_roster(chan)

    def _v_open_stats(self) -> None:
        if not self._v_results:
            return
        dlg = VideoSearchStatsDialog(self._v_results, self._db, self)
        dlg.exec()

    def _v_on_table_double_clicked(self, row: int, col: int) -> None:
        # Column 8 holds the action buttons — let them handle their own clicks.
        if col == 8:
            return
        item = self._v_table.item(row, 0)
        if item is None:
            return
        self._v_open_video(item.data(Qt.ItemDataRole.UserRole) or '')

    # ── render ────────────────────────────────────────────────────────

    def _render_results(self) -> None:
        sort = self._sort_combo.currentData() or 'potential'
        # Refresh the flagged state of each result from the DB so toggling
        # a flag in another window (e.g. the Candidate Pool) is reflected
        # here on the next render.
        flagged = {r['channel_id'] for r in self._db.get_candidate_pool()}
        for r in self._results:
            r['is_flagged'] = r['channel_id'] in flagged
        items = sorted(self._results, key=lambda r: {
            'potential': -r['potential_score'],
            'views_per_sub': -r['views_per_sub'],
            'subscribers': r['subscriber_count'],
            'views': -r['view_count'],
            'cadence': -r['cadence_per_week'],
        }.get(sort, -r['potential_score']))
        # Cache the sorted view so a width-only reflow (show/resize) can
        # rebuild just the cards grid without re-sorting or touching the table.
        self._sorted_items = items
        self._render_cards(items)

        # Table.
        self._table.setRowCount(len(items))
        for i, data in enumerate(items):
            name_item = QTableWidgetItem(data.get('title', ''))
            # Stash the channel_id on the row so a double-click can open the
            # creator's YouTube page without depending on sort order.
            name_item.setData(Qt.ItemDataRole.UserRole, data.get('channel_id', ''))
            name_item.setToolTip('Double-click to open on YouTube')
            self._table.setItem(i, 0, name_item)
            self._table.setItem(i, 1, QTableWidgetItem(_fmt_count(data.get('subscriber_count', 0))))
            self._table.setItem(i, 2, QTableWidgetItem(_fmt_count(data.get('view_count', 0))))
            self._table.setItem(i, 3, QTableWidgetItem(_fmt_ratio(data.get('views_per_sub', 0))))
            self._table.setItem(i, 4, QTableWidgetItem(f'{data.get("cadence_per_week", 0):.1f}'))
            self._table.setItem(i, 5, QTableWidgetItem(str(data.get('potential_score', 0))))
            actions = QWidget()
            ah = QHBoxLayout(actions)
            ah.setContentsMargins(2, 2, 2, 2)
            add = QPushButton('+')
            add.setToolTip('Add to roster')
            add.clicked.connect(lambda _, d=data: self.promote_to_roster(d))
            ev = QPushButton('Eval')
            ev.clicked.connect(lambda _, d=data: self.evaluate_creator(d))
            fl = QPushButton('⚑')
            fl.setToolTip('Flag')
            fl.clicked.connect(lambda _, d=data, b=fl: self.toggle_flag(d, b))
            ah.addWidget(add)
            ah.addWidget(ev)
            ah.addWidget(fl)
            ah.addStretch(1)
            self._table.setCellWidget(i, 6, actions)
        self._table.resizeColumnsToContents()
        self._table.setColumnWidth(0, 220)

    def _render_cards(self, items: list[dict[str, Any]]) -> None:
        # Drop existing cards.  setParent(None) detaches + hides immediately,
        # so a reflow doesn't briefly paint the old layout behind the new one
        # (deleteLater alone defers that to the next event-loop tick).
        while self._cards_grid.count():
            item = self._cards_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        cols = max(1, self._cards_scroll.viewport().width() // 260)
        for i, data in enumerate(items):
            card = _DiscoverCard(data, self)
            self._cards_grid.addWidget(card, i // cols, i % cols)

    def _reflow_cards(self) -> None:
        """Rebuild only the cards grid at the current viewport width.

        Triggered (debounced) on show + resize so the column count matches
        the real width instead of the stale pre-layout width the first
        ``_render_results`` ran with.  The table is left untouched.
        """
        items = getattr(self, '_sorted_items', None)
        if items is None:
            return
        self._render_cards(items)

    def _db_get_flagged(self, channel_id: str) -> bool:
        return self._db.is_candidate_flagged(channel_id)

    def _refresh_cache_label(self) -> None:
        count = self._db.count_cached_searches()
        self._cache_label.setText(f'{count} cached search{"es" if count != 1 else ""}')

    # ── per-card actions ──────────────────────────────────────────────

    def toggle_flag(self, data: dict[str, Any], btn: QPushButton) -> None:
        cid = data['channel_id']
        if self._db_get_flagged(cid):
            self._db.unflag_candidate(cid)
            btn.setText('⚑ Flag')
            data['is_flagged'] = False
        else:
            self._db.flag_candidate(cid)
            btn.setText('✓ Flagged')
            data['is_flagged'] = True
        self._refresh_candidates_badge()
        if self._on_pool_changed:
            self._on_pool_changed()

    def promote_to_roster(self, data: dict[str, Any]) -> None:
        roles = self._db.get_roles()
        if not roles:
            dark_warning(self, 'No roles', 'Create at least one role in Settings before promoting a creator.')
            return
        # Use the first role as the default (mirrors profile import behaviour).
        role_id = roles[0]['id']
        new_id = self._db.promote_candidate_to_roster(data['channel_id'], role_id)
        if new_id is None:
            dark_warning(self, 'Promotion failed', 'Creator not found in the discovered set.')
            return
        dark_info(self, 'Added to roster', f'{data.get("title", "Creator")} is now a tracked member. Use Refresh All to fetch their uploads.')
        if self._on_roster_changed:
            self._on_roster_changed()
        self._refresh_candidates_badge()
        if self._on_pool_changed:
            self._on_pool_changed()

    def evaluate_creator(self, data: dict[str, Any]) -> None:
        dlg = EvaluateDialog(self._db, data, self)
        dlg.exec()
        # The eval dialog shows the verdict itself and persists it to
        # ai_evaluations; it does not change flagged state or the result
        # set, so no grid re-render is needed here.

    def _on_open_candidates(self) -> None:
        """Open the flagged-candidate outreach pool (the Candidates tab)."""
        dlg = CandidatePoolDialog(
            self._db, self,
            on_roster_changed=self._on_roster_changed,
            on_pool_changed=self._on_pool_changed,
        )
        dlg.exec()
        # A promotion in the pool may have changed roster + pool state.
        self._refresh_candidates_badge()
        if self._on_roster_changed:
            self._on_roster_changed()

    def open_channel_page(self, channel_id: str) -> None:
        """Open a creator's YouTube channel page in the system default browser.

        Uses the canonical /channel/{id} URL (the UC… id), which resolves in
        any browser regardless of whether the creator has a custom handle.
        """
        cid = (channel_id or '').strip()
        if not cid:
            return
        QDesktopServices.openUrl(QUrl(f'https://www.youtube.com/channel/{cid}'))

    def _on_table_row_double_clicked(self, row: int, col: int) -> None:
        # Column 6 holds the action buttons — let them handle their own clicks.
        if col == 6:
            return
        item = self._table.item(row, 0)
        if item is None:
            return
        self.open_channel_page(item.data(Qt.ItemDataRole.UserRole) or '')

    def _refresh_candidates_badge(self) -> None:
        """Update the Discover window's Candidates button with the count."""
        try:
            n = self._db.get_candidate_count()
        except Exception:
            n = 0
        self._candidates_btn.setText(f'⚑ Candidates ({n})' if n else '⚑ Candidates')


class EvaluateDialog(QDialog):
    """On-demand single-prompt AI evaluation of a discovered creator."""

    def __init__(self, db: DatabaseManager, data: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._data = data
        self._worker: QThread | None = None
        self._list_worker: QThread | None = None
        self._saved_model: str | None = None
        self.setWindowTitle('AI Evaluation')
        self.setWindowIcon(create_app_icon())
        self.setMinimumSize(520, 460)
        self.setStyleSheet(build_dialog_qss())
        restore_geometry(self, 'EvaluateDialog', self._db)
        self.finished.connect(lambda _r: save_geometry(self, 'EvaluateDialog', self._db))
        self._build_ui()

    def _build_ui(self) -> None:
        vbox = QVBoxLayout(self)
        title = QLabel(f'AI Evaluation — {self._data.get("title", "")}')
        title.setObjectName('dialogTitle')
        vbox.addWidget(title)

        # Provider + model.
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel('Model:'))
        self._model_combo = QComboBox()
        _populate_model_combo(self._model_combo, self._db)
        # Remember the saved selection so a local model can be re-selected once
        # the async local-models fetch appends it.
        self._saved_model = (
            self._db.get_setting('discover_ai_model')
            or self._db.get_setting('auto_verify_model') or None
        )
        # Track whether the user has manually moved the combo so the async
        # local-models fetch doesn't override a deliberate pick made while
        # waiting for Ollama to respond.
        self._model_user_interacted = False
        self._model_combo.activated.connect(self._on_model_combo_interacted)
        self._load_local_models_async()
        model_row.addWidget(self._model_combo, 1)
        vbox.addLayout(model_row)

        # What we send summary.
        d = self._data
        info = QLabel(
            f"Channel: {d.get('title','')} ({d.get('handle','') or d.get('channel_id','')})\n"
            f"Subscribers: {d.get('subscriber_count',0):,} · Views: {d.get('view_count',0):,}\n"
            f"Cadence: {d.get('cadence_per_week',0):.1f}/wk · Views/sub: {d.get('views_per_sub',0):.1f}\n"
            f"Potential: {d.get('potential_score',0)}/100"
        )
        info.setStyleSheet(f'background: {C.BG_LAYER}; border: 1px solid {C.BORDER}; border-radius: 4px; padding: 8px;')
        info.setWordWrap(True)
        vbox.addWidget(info)

        self._run_btn = QPushButton('Evaluate (1 prompt)')
        self._run_btn.setObjectName('accentPrimary')
        self._run_btn.clicked.connect(self._on_run)
        vbox.addWidget(self._run_btn)

        # Show a previous evaluation if one exists.
        # The verdict/rationale text can be long, so the label lives inside a
        # QScrollArea — a bare QLabel with wordWrap clips anything taller than
        # the dialog's spare space, hiding the tail of the AI's reasoning.
        prev = self._db.get_latest_ai_evaluation(d.get('channel_id', ''))
        self._verdict_label = QLabel('')
        self._verdict_label.setWordWrap(True)
        # Plain-text format so model output can't render <img>/HTML and trigger
        # outbound requests or rich-text injection.
        self._verdict_label.setTextFormat(Qt.TextFormatFlag.PlainText)
        self._verdict_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._verdict_label.setStyleSheet(f'color: {C.TEXT_PRIMARY};')
        inner = QWidget()
        inner.setStyleSheet(f'background: {C.BG_LAYER};')
        inner_v = QVBoxLayout(inner)
        inner_v.setContentsMargins(8, 8, 8, 8)
        inner_v.addWidget(self._verdict_label)
        self._verdict_scroll = QScrollArea()
        self._verdict_scroll.setWidgetResizable(True)
        self._verdict_scroll.setFrameShape(QFrame.Shape.StyledPanel)
        self._verdict_scroll.setStyleSheet(
            f'QScrollArea {{ background: {C.BG_LAYER}; border: 1px solid {C.BORDER}; border-radius: 4px; }}'
            f' QScrollBar:vertical {{ background: {C.BG_RAISED}; width: 10px; }}'
            f' QScrollBar::handle:vertical {{ background: {C.BORDER}; border-radius: 4px; min-height: 24px; }}'
            f' QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}'
        )
        self._verdict_scroll.setWidget(inner)
        vbox.addWidget(self._verdict_scroll, 1)
        if prev:
            self._verdict_label.setText(f'Previous verdict: {prev["verdict"]}\n\n{prev["rationale"]}')

        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.accept)
        vbox.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _on_run(self) -> None:
        if self._worker is not None:
            if self._worker.isRunning():
                return
            self._worker.deleteLater()
        model = self._model_combo.currentData()
        self._db.set_setting('discover_ai_model', model)
        self._run_btn.setEnabled(False)
        self._verdict_label.setStyleSheet(f'color: {C.TEXT_SECONDARY};')
        self._verdict_label.setText('Asking the AI…')
        self._verdict_scroll.ensureVisible(0, 0)
        self._worker = EvaluateWorker(self._db, self._data.get('channel_id', ''), model)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.api_key_missing.connect(self._on_error)
        self._worker.aborted.connect(lambda: self._verdict_label.setText(
            'Evaluation cancelled (profile switched).'))
        self._worker.finished.connect(lambda: self._run_btn.setEnabled(True))
        self._worker.start()

    def _load_local_models_async(self) -> None:
        """Fetch installed local models off the GUI thread and append them to
        the combo when Ollama responds, so opening this dialog never blocks.
        """
        worker = ListLocalModelsWorker(get_ollama_host(self._db))
        self._list_worker = worker
        worker.done.connect(self._on_local_models_done)
        worker.error.connect(self._on_local_models_error)
        worker.finished.connect(self._retire_list_worker)
        worker.start()

    def _on_model_combo_interacted(self, _index: int) -> None:
        self._model_user_interacted = True

    def _on_local_models_done(self, tags: list) -> None:
        if sip.isdeleted(self) or sip.isdeleted(self._model_combo):
            return
        for tag in tags:
            self._model_combo.addItem(f'Local {tag}', f'ollama:{tag}')
        # Re-select the saved model if it's a local one that just appeared — but
        # only if the user hasn't already moved off the cloud fallback
        # (currentIndex == 0 means the saved model wasn't a cloud one, so the
        # combo was left on the first cloud item). We never override a
        # deliberate pick made while waiting for Ollama.
        if (not self._model_user_interacted
                and self._saved_model and self._saved_model.startswith('ollama:')
                and self._model_combo.currentIndex() == 0):
            for i in range(self._model_combo.count()):
                if self._model_combo.itemData(i) == self._saved_model:
                    self._model_combo.setCurrentIndex(i)
                    break

    def _on_local_models_error(self, _msg: str) -> None:
        # Ollama not running → no local models to append; nothing to do.
        pass

    def _retire_list_worker(self) -> None:
        self._list_worker = None

    def closeEvent(self, event) -> None:  # noqa: N802
        # Don't let a running AI worker be destroyed with the dialog.
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            _retire_worker(self._worker)
        self._worker = None
        # Drop an in-flight local-models fetch too; it self-retires via the
        # module-level registry in core.local_llm.
        w = self._list_worker
        if w is not None and not sip.isdeleted(w):
            # Disconnect only the GUI-mutating signals; leave ``finished``
            # connected so the worker's self-cleanup lambda (registered in
            # ListLocalModelsWorker.start) still discards it from
            # _LIVE_LIST_WORKERS and deleteLater()s it.
            for name in ('done', 'error'):
                try:
                    getattr(w, name).disconnect()
                except (TypeError, RuntimeError):
                    pass
        self._list_worker = None
        super().closeEvent(event)

    def _on_done(self, verdict: str, rationale: str, raw: str) -> None:
        color = C.SUCCESS if 'Worth' in verdict else (C.DANGER if 'Not worth' in verdict else C.TEXT_SECONDARY)
        self._verdict_label.setStyleSheet(f'color: {color};')
        self._verdict_label.setText(f'Verdict: {verdict}\n\n{rationale}')
        # Jump to the top so the verdict + start of the rationale is visible.
        self._verdict_scroll.ensureVisible(0, 0)

    def _on_error(self, msg: str) -> None:
        self._verdict_label.setStyleSheet(f'color: {C.DANGER};')
        self._verdict_label.setText(f'Error: {msg}')