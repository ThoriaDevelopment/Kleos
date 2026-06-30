from __future__ import annotations
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.dates import date2num
from matplotlib.figure import Figure
from PyQt6 import sip
from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRect, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPixmap
from PyQt6.QtWidgets import QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea, QStackedWidget, QTabWidget, QTextEdit, QVBoxLayout, QWidget
from core.cache_manager import ensure_thumbnail
from core.db_manager import DatabaseManager
from ui.app_icon import create_app_icon
from ui.components.creator_card import relative_time, format_subscriber_count
from ui.dialog_utils import dark_question, enable_window_maximize, handle_fullscreen_keypress
from ui.chart_common import apply_style, build_conditions, smooth_mpl_patch
from ui.chart_utils import _ZoomableFigureCanvas
from ui.geometry import restore_geometry, save_geometry
from ui.theme import C
from ui.theme.stylesheet import build_dialog_qss, qss_refresh

def _content_url(platform: str, content_id: str, channel_name: str = '') -> str:
    if platform == 'youtube':
        return f'https://www.youtube.com/watch?v={content_id}'
    else:
        if platform == 'twitch':
            # Past broadcasts use video IDs; live streams use stream IDs.
            # Stream IDs are not valid on /videos/, so fall back to the channel page.
            if content_id.startswith('v') or content_id.isdigit():
                return f'https://www.twitch.tv/videos/{content_id}'
            if channel_name:
                return f'https://www.twitch.tv/{channel_name}'
            return f'https://www.twitch.tv/videos/{content_id}'
        else:
            return ''
def _placeholder_pixmap(w: int=120, h: int=68) -> QPixmap:
    px = QPixmap(w, h)
    px.fill(QColor(C.DIALOG_BG))
    return px
class _ContentRow(QFrame):
    """One row in the history list representing a single piece of media."""
    thumbnail_loaded = pyqtSignal(str)
    content_type_changed = pyqtSignal()
    def __init__(self, media: dict[str, Any], db: DatabaseManager, on_verified_changed: Callable[[], None], parent: QWidget | None=None, *, channel_name: str = '', thumb_pool: ThreadPoolExecutor | None=None) -> None:
        super().__init__(parent)
        self._media = dict(media)
        self._db = db
        self._on_verified_changed = on_verified_changed
        self._thumb_pool = thumb_pool
        self._content_url = _content_url(media.get('platform', ''), media.get('content_id', ''), channel_name)
        self._thumbnail_url = media.get('thumbnail_url', '') or ''
        self.thumbnail_loaded.connect(self._on_thumbnail_loaded)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(80)
        self.setMaximumHeight(100)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.setObjectName('mediaRow')
        self._build_ui()
    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)
        thumb_path = self._media.get('thumbnail_path', '')
        self._thumb_label = QLabel()
        self._thumb_label.setFixedSize(120, 68)
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setObjectName('mediaThumb')
        self._load_thumbnail(thumb_path)
        layout.addWidget(self._thumb_label)
        mid = QVBoxLayout()
        mid.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_text = self._media.get('title', 'Untitled')
        self._title_label = QLabel(title_text)
        self._title_label.setWordWrap(True)
        self._title_label.setMaximumHeight(40)
        title_font = QFont()
        title_font.setPointSize(10)
        self._title_label.setFont(title_font)
        self._title_label.setObjectName('mediaLabel')
        title_row.addWidget(self._title_label, 1)
        self._type_badge = QLabel()
        self._type_badge.setObjectName('typeBadge')
        self._type_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._update_type_badge()
        title_row.addWidget(self._type_badge)
        mid.addLayout(title_row)
        upload_date = self._media.get('upload_date', '')
        self._age_label = QLabel(relative_time(upload_date))
        self._age_label.setObjectName('mediaMeta')
        mid.addWidget(self._age_label)
        layout.addLayout(mid, 1)
        verified = bool(self._media.get('is_verified', 0))
        self._verify_btn = QPushButton()
        self._verify_btn.setFixedSize(110, 32)
        self._verify_btn.setObjectName('verifyBtn')
        self._verify_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._set_verify_style(verified)
        self._verify_btn.clicked.connect(self._toggle_verified)
        layout.addWidget(self._verify_btn)
        views = self._media.get('view_count', 0)
        self._views_label = QLabel(f'{views:,}')
        views_font = QFont()
        views_font.setBold(True)
        views_font.setPointSize(11)
        self._views_label.setFont(views_font)
        self._views_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._views_label.setMinimumWidth(80)
        self._views_label.setObjectName('mediaLabel')
        layout.addWidget(self._views_label)
    def _load_thumbnail(self, path: str) -> None:
        if path and Path(path).exists() and (Path(path).stat().st_size > 0):
            px = QPixmap(path)
            if not px.isNull():
                scaled = px.scaled(120, 68, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                self._thumb_label.setPixmap(scaled)
                return None
        self._thumb_label.setPixmap(_placeholder_pixmap())
        if self._thumbnail_url:
            url = self._thumbnail_url
            if self._thumb_pool is not None:
                future = self._thumb_pool.submit(ensure_thumbnail, url)
                future.add_done_callback(self._on_thumb_future)
            else:
                def _recover():
                    new_path = ensure_thumbnail(url)
                    if new_path:
                        self.thumbnail_loaded.emit(new_path)
                threading.Thread(target=_recover, daemon=True).start()

    def _on_thumb_future(self, future) -> None:
        """Callback when a thumbnail download completes via the thread pool."""
        if sip.isdeleted(self):
            return
        try:
            new_path = future.result()
        except Exception:
            new_path = None
        if new_path:
            self.thumbnail_loaded.emit(new_path)
    def reload_thumbnail(self, path: str) -> None:
        self._load_thumbnail(path)
    def _on_thumbnail_loaded(self, path: str) -> None:
        """Slot called on the main thread when a background thumbnail download completes."""
        try:
            if sip.isdeleted(self) or sip.isdeleted(self._thumb_label):
                return
            px = QPixmap(path)
            if not px.isNull():
                scaled = px.scaled(120, 68, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                self._thumb_label.setPixmap(scaled)
        except Exception:
            pass
    def _set_verify_style(self, verified: bool) -> None:
        self._verify_btn.setProperty('verified', 'true' if verified else 'false')
        self._verify_btn.setText('In Community' if verified else 'Verify')
        qss_refresh(self._verify_btn)
    def _toggle_verified(self) -> None:
        current = bool(self._media.get('is_verified', 0))
        new_val = not current
        content_id = self._media.get('content_id', '')
        if content_id:
            self._db.set_verified(content_id, new_val)
            self._media['is_verified'] = int(new_val)
            self._set_verify_style(new_val)
            if self._on_verified_changed:
                self._on_verified_changed()

    def _effective_type(self) -> str:
        """Return the effective content type: 'short', 'stream', or 'video'."""
        override = self._media.get('type_override')
        if override:
            return override
        if self._media.get('is_stream'):
            return 'stream'
        if self._media.get('is_short'):
            return 'short'
        return 'video'

    def _update_type_badge(self) -> None:
        """Refresh the type badge label to reflect current state."""
        ct = self._effective_type()
        override = self._media.get('type_override')
        labels = {'short': 'Short', 'stream': 'Stream', 'video': 'Video'}
        text = labels.get(ct, 'Video')
        if override:
            text += ' ✎'  # pencil indicator for manual override
        self._type_badge.setText(text)
        self._type_badge.setProperty('ct', ct)
        qss_refresh(self._type_badge)

    def _show_context_menu(self, pos) -> None:
        """Show a context menu for setting the content type."""
        menu = QMenu(self)
        ct = self._effective_type()
        content_id = self._media.get('content_id', '')
        if not content_id:
            menu.exec(self.mapToGlobal(pos))
            return

        act_video = menu.addAction('Set as Video')
        act_video.setCheckable(True)
        act_video.setChecked(ct == 'video')
        act_short = menu.addAction('Set as Short')
        act_short.setCheckable(True)
        act_short.setChecked(ct == 'short')
        act_stream = menu.addAction('Set as Stream')
        act_stream.setCheckable(True)
        act_stream.setChecked(ct == 'stream')
        menu.addSeparator()
        act_reset = menu.addAction('Reset to Auto-Detect')
        act_reset.setEnabled(bool(self._media.get('type_override')))
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_video:
            self._db.set_type_override(content_id, 'video')
            self._media['is_short'] = 0
            self._media['is_stream'] = 0
            self._media['type_override'] = 'video'
        elif chosen == act_short:
            self._db.set_type_override(content_id, 'short')
            self._media['is_short'] = 1
            self._media['is_stream'] = 0
            self._media['type_override'] = 'short'
        elif chosen == act_stream:
            self._db.set_type_override(content_id, 'stream')
            self._media['is_short'] = 0
            self._media['is_stream'] = 1
            self._media['type_override'] = 'stream'
        elif chosen == act_reset:
            self._db.set_type_override(content_id, None)
            self._media['type_override'] = None
            # Note: is_short/is_stream will be corrected on next refetch
        self._update_type_badge()
        self.content_type_changed.emit()
    def refresh_time(self) -> None:
        self._age_label.setText(relative_time(self._media.get('upload_date', '')))
    def mouseDoubleClickEvent(self, event) -> None:
        if self._content_url:
            threading.Thread(target=webbrowser.open, args=(self._content_url,), daemon=True).start()
        super().mouseDoubleClickEvent(event)
class _CreatorTimelineChart(_ZoomableFigureCanvas, FigureCanvas):
    """Line chart of view counts over time for a single creator's content.

    Supports scroll-to-zoom, drag-to-pan, and double-click-to-reset.
    """

    def __init__(self, db: DatabaseManager, creator_id: int, parent: QWidget | None = None) -> None:
        self._fig = Figure(figsize=(5, 2.5), dpi=100)
        super().__init__(self._fig)
        self._db = db
        self._creator_id = creator_id
        self._verified_only = True
        self._content_type = None
        self._time_range = None
        self._pan_active = False
        self._home_xlim = None
        self._home_ylim = None
        self.setParent(parent)
        self.setMinimumHeight(200)
        self.setStyleSheet('background: transparent;')
        self._render()

    def set_verified_only(self, verified_only: bool) -> None:
        """Toggle verification filter and re-render."""
        self._verified_only = verified_only
        self._render()

    def set_content_type(self, content_type: str | None) -> None:
        """Set content-type filter (None=all, 'short', 'video', 'stream') and re-render."""
        self._content_type = content_type
        self._render()

    def set_time_range(self, time_range: str | None) -> None:
        """Set time-range filter (None=all, 'week', 'month', 'year') and re-render."""
        self._time_range = time_range
        self._render()

    def _render(self) -> None:
        self._fig.clear()
        self._series_data = []
        ax = self._fig.add_subplot(111)
        conditions, params = build_conditions(
            verified_only=self._verified_only, content_type=self._content_type,
            time_range=self._time_range, creator_id=self._creator_id, table_prefix='',
        )
        where = ' AND '.join(conditions)
        rows = self._db._read(
            f'SELECT upload_date, view_count FROM media_content WHERE {where} ORDER BY upload_date ASC',
            tuple(params),
        )
        type_labels: dict[str | None, str] = {None: 'Content', 'short': 'Shorts', 'video': 'Videos', 'stream': 'Streams'}
        label = f"{'Verified' if self._verified_only else 'All'} {type_labels.get(self._content_type, 'Content')}"
        if not rows:
            ax.text(0.5, 0.5, f'No {label.lower()} yet', ha='center', va='center', fontsize=12, color='#888')
            apply_style(self._fig)
            self.draw()
            self._save_home_limits()
        else:
            dates = []
            views = []
            for r in rows:
                try:
                    dt = datetime.fromisoformat(r['upload_date'].replace('Z', '+00:00'))
                    dates.append(dt)
                    views.append(r['view_count'])
                except (ValueError, TypeError):
                    pass
            if not dates:
                ax.text(0.5, 0.5, 'No parseable dates', ha='center', va='center', fontsize=12, color='#888')
                apply_style(self._fig)
                self.draw()
                self._save_home_limits()
            else:
                patch = smooth_mpl_patch(date2num(dates), views, C.ACCENT,
                                        floor=0.0, linewidth=1.5, zorder=3)
                if patch is not None:
                    ax.add_patch(patch)
                ax.scatter(dates, views, marker='o', s=16, color=C.ACCENT, zorder=4)
                self._series_data.append({
                    'xnum': date2num(dates), 'dates': dates,
                    'views': views, 'label': '',
                })
                ax.set_xlabel('Date')
                ax.set_ylabel('Views')
                ax.set_title(f'{label} — View Trajectory')
                apply_style(self._fig)
                self._fig.autofmt_xdate()
                self.draw()
                self._save_home_limits()
class _CreatorBarChart(_ZoomableFigureCanvas, FigureCanvas):
    """Bar chart of monthly upload counts for a single creator.

    Supports scroll-to-zoom, drag-to-pan, and double-click-to-reset.
    """

    def __init__(self, db: DatabaseManager, creator_id: int, parent: QWidget | None = None) -> None:
        self._fig = Figure(figsize=(5, 2.5), dpi=100)
        super().__init__(self._fig)
        self._db = db
        self._creator_id = creator_id
        self._verified_only = True
        self._content_type = None
        self._time_range = None
        self._pan_active = False
        self._home_xlim = None
        self._home_ylim = None
        self.setParent(parent)
        self.setMinimumHeight(200)
        self.setStyleSheet('background: transparent;')
        self._render()

    def set_verified_only(self, verified_only: bool) -> None:
        """Toggle verification filter and re-render."""
        self._verified_only = verified_only
        self._render()

    def set_content_type(self, content_type: str | None) -> None:
        """Set content-type filter (None=all, 'short', 'video', 'stream') and re-render."""
        self._content_type = content_type
        self._render()

    def set_time_range(self, time_range: str | None) -> None:
        """Set time-range filter (None=all, 'week', 'month', 'year') and re-render."""
        self._time_range = time_range
        self._render()

    def _render(self) -> None:
        self._fig.clear()
        ax = self._fig.add_subplot(111)
        conditions, params = build_conditions(
            verified_only=self._verified_only, content_type=self._content_type,
            time_range=self._time_range, creator_id=self._creator_id, table_prefix='',
        )
        where = ' AND '.join(conditions)
        rows = self._db._read(
            f'SELECT upload_date FROM media_content WHERE {where} ORDER BY upload_date ASC',
            tuple(params),
        )
        type_labels: dict[str | None, str] = {None: 'Uploads', 'short': 'Shorts', 'video': 'Videos', 'stream': 'Streams'}
        label = f"{'Verified' if self._verified_only else 'All'} {type_labels.get(self._content_type, 'Uploads')}"
        if not rows:
            ax.text(0.5, 0.5, f'No {label.lower()} yet', ha='center', va='center', fontsize=12, color='#888')
            apply_style(self._fig)
            self.draw()
            self._save_home_limits()
        else:
            month_counts = defaultdict(int)
            for r in rows:
                try:
                    dt = datetime.fromisoformat(r['upload_date'].replace('Z', '+00:00'))
                    key = dt.strftime('%Y-%m')
                    month_counts[key] += 1
                except (ValueError, TypeError):
                    pass
            months = sorted(month_counts.keys())
            counts = [month_counts[m] for m in months]
            labels = []
            for m in months:
                try:
                    dt = datetime.strptime(m, '%Y-%m')
                    labels.append(dt.strftime('%b %y'))
                except ValueError:
                    labels.append(m)
            ax.bar(range(len(months)), counts, color=C.ACCENT, width=0.6, edgecolor=C.BORDER, linewidth=0.5)
            ax.set_xticks(range(len(months)))
            ax.set_xticklabels(labels, rotation=45, fontsize=8)
            ax.set_ylabel('Uploads')
            ax.set_title(f'Monthly {label}')
            apply_style(self._fig)
            self._fig.tight_layout()
            self.draw()
            self._save_home_limits()
class HistoryDialog(QDialog):
    """Modal showing chronological media history for a single creator.

Entry animation: scales from 88 % → 100 % + opacity 0 → 1 over 280 ms
using OutExpo easing for a premium feel.

Paginated rendering: only _PAGE_SIZE rows are created at a time.
A "Load More" button at the bottom appends the next batch,
keeping the UI responsive even with 1000+ videos.
"""
    verified_changed = pyqtSignal()
    member_deleted = pyqtSignal(int)
    _PAGE_SIZE = 50

    def __init__(self, creator: dict[str, Any], db: DatabaseManager, parent: QWidget | None=None, *, on_refresh: Callable[[int], None] | None=None) -> None:
        super().__init__(parent)
        enable_window_maximize(self)
        self._creator = creator
        self._db = db
        self._thumb_pool = ThreadPoolExecutor(max_workers=4)
        self._rows: list[_ContentRow] = []
        self._all_media: list[dict[str, Any]] = []
        self._display_media: list[dict[str, Any]] = []
        self._rendered_count = 0
        self._on_refresh = on_refresh
        nickname = creator.get('nickname', 'Unknown')
        self.setWindowTitle(f'Media History — {nickname}')
        self.setWindowIcon(create_app_icon())
        self.setMinimumSize(680, 480)
        self.resize(780, 560)
        self.reapply_theme()
        restore_geometry(self, 'HistoryDialog', self._db)
        self.finished.connect(lambda _r: save_geometry(self, 'HistoryDialog', self._db))
        self._build_ui()
        self._animated = False
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)
    def reapply_theme(self) -> None:
        """Rebuild the dialog stylesheet and recolor charts from live tokens."""
        self.setStyleSheet(build_dialog_qss())
        # On-demand charts read C.* inside _render(); re-render so they follow
        # a theme switch without reopening the dialog.
        for chart in (getattr(self, '_creator_timeline', None), getattr(self, '_creator_bar', None)):
            if chart is not None and not sip.isdeleted(chart):
                chart._render()
    def _animate_entry(self) -> None:
        """Scale + fade in from screen center using OutExpo curve."""
        final_geo = self.geometry()
        shrink = 0.88
        w_small = int(final_geo.width() * shrink)
        h_small = int(final_geo.height() * shrink)
        start_geo = QRect(final_geo.x() + (final_geo.width() - w_small) // 2, final_geo.y() + (final_geo.height() - h_small) // 2, w_small, h_small)
        geo_anim = QPropertyAnimation(self, b'geometry', self)
        geo_anim.setDuration(280)
        geo_anim.setStartValue(start_geo)
        geo_anim.setEndValue(final_geo)
        geo_anim.setEasingCurve(QEasingCurve.Type.OutExpo)
        op_anim = QPropertyAnimation(self._opacity_effect, b'opacity', self)
        op_anim.setDuration(260)
        op_anim.setStartValue(0.0)
        op_anim.setEndValue(1.0)
        op_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        op_anim.finished.connect(lambda: self.setGraphicsEffect(None))
        geo_anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        op_anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._animated:
            self._animated = True
            self._animate_entry()
    def keyPressEvent(self, event) -> None:  # noqa: N802
        if handle_fullscreen_keypress(self, event):
            return
        super().keyPressEvent(event)

    def _build_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(16, 12, 16, 12)
        vbox.setSpacing(10)
        self._build_header(vbox)
        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(self._on_tab_changed)
        vbox.addWidget(self._tabs, 1)
        # --- Sort / Filter / Search control bar ---
        control_bar = QHBoxLayout()
        control_bar.setSpacing(8)
        self._sort_combo = QComboBox()
        self._sort_combo.addItems(['Date (newest)', 'Date (oldest)', 'Title A-Z', 'Views (high-low)'])
        self._sort_combo.setMinimumWidth(130)
        self._sort_combo.currentIndexChanged.connect(self._apply_sort_filter)
        control_bar.addWidget(self._sort_combo)

        self._filter_combo = QComboBox()
        self._filter_combo.addItems(['All', 'Verified only', 'Shorts only', 'Videos only', 'Streams only'])
        self._filter_combo.setMinimumWidth(120)
        self._filter_combo.currentIndexChanged.connect(self._apply_sort_filter)
        control_bar.addWidget(self._filter_combo)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText('Search content...')
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._apply_sort_filter)
        self._search_edit.textChanged.connect(self._search_timer.start)
        control_bar.addWidget(self._search_edit, 1)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.viewport().setObjectName('historyViewport')
        self._list_container = QWidget()
        self._list_container.setObjectName('historyList')
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._list_layout.setSpacing(6)
        self._list_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinAndMaxSize)
        self._scroll.setWidget(self._list_container)
        # Footer with count and load-more button sits OUTSIDE the scroll area
        # so it's always visible without scrolling to the bottom
        media_page = QWidget()
        media_layout = QVBoxLayout(media_page)
        media_layout.setContentsMargins(0, 0, 0, 0)
        media_layout.setSpacing(6)
        media_layout.addLayout(control_bar)
        media_layout.addWidget(self._scroll, 1)
        self._count_label = QLabel()
        self._count_label.setObjectName('historyCount')
        self._count_label.setProperty('state', 'more')
        media_layout.addWidget(self._count_label)
        self._load_more_btn = QPushButton('Load More')
        self._load_more_btn.setObjectName('loadMoreBtn')
        self._load_more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._load_more_btn.clicked.connect(self._load_more)
        media_layout.addWidget(self._load_more_btn)
        self._tabs.addTab(media_page, 'Media')
        stats_page = QWidget()
        stats_layout = QVBoxLayout(stats_page)
        stats_layout.setContentsMargins(4, 8, 4, 4)
        stats_layout.setSpacing(8)
        filter_row = QHBoxLayout()
        self._verified_check = QCheckBox('Verified only')
        self._verified_check.setChecked(False)
        self._verified_check.stateChanged.connect(self._on_verified_check_changed)
        filter_row.addWidget(self._verified_check)
        filter_row.addWidget(QLabel('Type:'))
        self._stats_type_combo = QComboBox()
        self._stats_type_combo.addItem('All types', None)
        self._stats_type_combo.addItem('Shorts', 'short')
        self._stats_type_combo.addItem('Videos', 'video')
        self._stats_type_combo.addItem('Streams', 'stream')
        self._stats_type_combo.currentIndexChanged.connect(self._on_stats_type_changed)
        filter_row.addWidget(self._stats_type_combo)
        filter_row.addWidget(QLabel('Range:'))
        self._stats_range_combo = QComboBox()
        self._stats_range_combo.addItem('All time', None)
        self._stats_range_combo.addItem('Last year', 'year')
        self._stats_range_combo.addItem('Last month', 'month')
        self._stats_range_combo.addItem('Last week', 'week')
        self._stats_range_combo.currentIndexChanged.connect(self._on_stats_range_changed)
        filter_row.addWidget(self._stats_range_combo)
        filter_row.addStretch(1)
        filter_row.addWidget(QLabel('Chart:'))
        self._btn_timeline = QPushButton('Timeline')
        self._btn_timeline.setObjectName('chartToggle')
        self._btn_timeline.setCheckable(True)
        self._btn_timeline.setChecked(True)
        self._btn_timeline.clicked.connect(lambda: self._chart_stack.setCurrentIndex(0))
        filter_row.addWidget(self._btn_timeline)
        self._btn_bar = QPushButton('Upload Activity')
        self._btn_bar.setObjectName('chartToggle')
        self._btn_bar.setCheckable(True)
        self._btn_bar.clicked.connect(lambda: self._chart_stack.setCurrentIndex(1))
        filter_row.addWidget(self._btn_bar)
        chart_group = QButtonGroup(self)
        chart_group.setExclusive(True)
        chart_group.addButton(self._btn_timeline)
        chart_group.addButton(self._btn_bar)
        stats_layout.addLayout(filter_row)
        self._chart_stack = QStackedWidget()
        self._creator_timeline = None
        self._creator_bar = None
        self._chart_stack.addWidget(QWidget())  # placeholder for timeline
        self._chart_stack.addWidget(QWidget())  # placeholder for bar
        stats_layout.addWidget(self._chart_stack, 1)

        # ── Report row (scoped to this creator) ──
        report_row = QHBoxLayout()
        report_row.addWidget(QLabel('Report:'))
        self._report_period_combo = QComboBox()
        self._report_period_combo.addItem('Monthly', 'monthly')
        self._report_period_combo.addItem('Weekly', 'weekly')
        self._report_period_combo.addItem('Yearly', 'yearly')
        self._report_period_combo.addItem('All time', 'all')
        report_row.addWidget(self._report_period_combo)
        self._report_verified_check = QCheckBox('Verified only')
        report_row.addWidget(self._report_verified_check)
        report_row.addWidget(QLabel('Type:'))
        self._report_type_combo = QComboBox()
        self._report_type_combo.addItem('All types', None)
        self._report_type_combo.addItem('Shorts', 'short')
        self._report_type_combo.addItem('Videos', 'video')
        self._report_type_combo.addItem('Streams', 'stream')
        report_row.addWidget(self._report_type_combo)
        self._report_btn = QPushButton('Copy Report')
        self._report_btn.clicked.connect(self._on_copy_report)
        report_row.addWidget(self._report_btn)
        self._html_btn = QPushButton('Export HTML')
        self._html_btn.clicked.connect(self._on_export_html)
        report_row.addWidget(self._html_btn)
        report_row.addStretch(1)
        stats_layout.addLayout(report_row)

        self._tabs.addTab(stats_page, 'Stats')
        close = QPushButton('Close')
        close.setFixedWidth(100)
        close.clicked.connect(self.accept)
        vbox.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        self._load_content()
    def _build_header(self, parent_layout: QVBoxLayout) -> None:
        header = QFrame()
        header.setObjectName('historyHeader')
        h_layout = QVBoxLayout(header)
        h_layout.setSpacing(4)
        h_layout.setContentsMargins(12, 10, 12, 10)
        name_row = QHBoxLayout()
        nick = self._creator.get('nickname', 'Unknown')
        name_label = QLabel(nick)
        name_font = QFont()
        name_font.setBold(True)
        name_font.setPointSize(14)
        name_label.setFont(name_font)
        name_label.setObjectName('cardName')
        name_row.addWidget(name_label)
        sub_counts = self._db.bulk_subscriber_counts().get(self._creator['id'], {})
        sub_text = format_subscriber_count(sub_counts.get('youtube', 0), sub_counts.get('twitch', 0))
        if sub_text != 'N/A':
            sub_label = QLabel(sub_text)
            sub_label.setObjectName('countLabel')
            name_row.addWidget(sub_label)
        name_row.addStretch(1)
        self._refresh_btn = QPushButton('Refresh Content')
        self._refresh_btn.setObjectName('refreshContentBtn')
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.clicked.connect(self._on_refresh_content)
        name_row.addWidget(self._refresh_btn)
        self._delete_btn = QPushButton('Delete Member')
        self._delete_btn.setObjectName('deleteMemberBtn')
        self._delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_btn.clicked.connect(self._on_delete_member)
        name_row.addWidget(self._delete_btn)
        self._export_btn = QPushButton('Export')
        self._export_btn.setObjectName('exportCreatorBtn')
        self._export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._export_btn.clicked.connect(self._on_export_creator)
        name_row.addWidget(self._export_btn)
        h_layout.addLayout(name_row)
        self._last_verified_label = QLabel()
        self._last_verified_label.setObjectName('cardActivity')
        self._update_last_verified()
        h_layout.addWidget(self._last_verified_label)
        # Notes section
        notes_label = QLabel('Notes:')
        notes_label.setObjectName('cardActivity')
        h_layout.addWidget(notes_label)
        self._notes_edit = QTextEdit()
        self._notes_edit.setObjectName('notesEdit')
        self._notes_edit.setPlaceholderText('Add notes about this member…')
        self._notes_edit.setMaximumHeight(60)
        self._notes_edit.setPlainText(self._creator.get('notes', '') or '')
        self._notes_timer = QTimer(self)
        self._notes_timer.setSingleShot(True)
        self._notes_timer.setInterval(500)
        self._notes_timer.timeout.connect(self._save_notes)
        self._notes_edit.textChanged.connect(self._notes_timer.start)
        h_layout.addWidget(self._notes_edit)
        self._notes_save_label = QLabel('')
        self._notes_save_label.setObjectName('countLabel')
        h_layout.addWidget(self._notes_save_label)
        self._notes_save_clear_timer = QTimer(self)
        self._notes_save_clear_timer.setSingleShot(True)
        self._notes_save_clear_timer.setInterval(2000)
        self._notes_save_clear_timer.timeout.connect(lambda: self._notes_save_label.setText(''))
        parent_layout.addWidget(header)
    def _update_last_verified(self) -> None:
        media = self._all_media or self._db.get_media(creator_id=self._creator['id'])
        verified_dates = [m['upload_date'] for m in media if m.get('is_verified') == 1 and m.get('upload_date')]
        if verified_dates:
            verified_dates.sort(reverse=True)
            elapsed = relative_time(verified_dates[0])
            self._last_verified_label.setText(f'Last verified content: {elapsed}')
        else:
            self._last_verified_label.setText('No verified content yet')
    def _load_content(self) -> None:
        """Clear existing rows, populate _all_media, then apply sort/filter."""
        # Remove only content rows from the list layout
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows.clear()
        self._all_media = self._db.get_media(creator_id=self._creator['id'])
        self._apply_sort_filter()

    def _apply_sort_filter(self) -> None:
        """Filter and sort _all_media into _display_media, then render."""
        media = list(self._all_media)

        # Filter
        filter_idx = self._filter_combo.currentIndex()
        if filter_idx == 1:  # Verified only
            media = [m for m in media if m.get('is_verified', 0)]
        elif filter_idx == 2:  # Shorts only
            media = [m for m in media if m.get('is_short', 0)]
        elif filter_idx == 3:  # Videos only (not short, not stream)
            media = [m for m in media if not m.get('is_short', 0) and not m.get('is_stream', 0)]
        elif filter_idx == 4:  # Streams only (Twitch or YouTube streams)
            media = [m for m in media if m.get('is_stream', 0)]

        # Search
        search_text = self._search_edit.text().strip().lower()
        if search_text:
            media = [m for m in media if search_text in (m.get('title', '') or '').lower()]

        # Sort
        sort_idx = self._sort_combo.currentIndex()
        if sort_idx == 0:  # Date (newest)
            media.sort(key=lambda m: m.get('upload_date', '') or '', reverse=True)
        elif sort_idx == 1:  # Date (oldest)
            media.sort(key=lambda m: m.get('upload_date', '') or '')
        elif sort_idx == 2:  # Title A-Z
            media.sort(key=lambda m: (m.get('title', '') or '').lower())
        elif sort_idx == 3:  # Views (high-low)
            media.sort(key=lambda m: m.get('view_count', 0) or 0, reverse=True)

        self._display_media = media
        self._render_filtered_content()

    def _render_filtered_content(self) -> None:
        """Clear existing rows and render the first page of _display_media."""
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows.clear()
        self._rendered_count = 0
        self._list_container.blockSignals(True)
        self._scroll.blockSignals(True)
        self._render_next_page()
        self._list_container.blockSignals(False)
        self._scroll.blockSignals(False)
        self._list_container.updateGeometry()
        self._scroll.updateGeometry()

    def _on_tab_changed(self, index: int) -> None:
        """Lazily create charts when the Stats tab is first shown."""
        if self._tabs.tabText(index) != 'Stats' or self._creator_timeline is not None:
            return
        verified_only = self._verified_check.isChecked()
        content_type = self._stats_type_combo.currentData()
        self._creator_timeline = _CreatorTimelineChart(self._db, self._creator['id'])
        self._creator_timeline.set_verified_only(verified_only)
        self._creator_timeline.set_content_type(content_type)
        self._chart_stack.removeWidget(self._chart_stack.widget(0))
        self._chart_stack.insertWidget(0, self._creator_timeline)
        self._creator_bar = _CreatorBarChart(self._db, self._creator['id'])
        self._creator_bar.set_verified_only(verified_only)
        self._creator_bar.set_content_type(content_type)
        self._chart_stack.removeWidget(self._chart_stack.widget(1))
        self._chart_stack.insertWidget(1, self._creator_bar)
        self._chart_stack.setCurrentIndex(0 if self._btn_timeline.isChecked() else 1)

    def _render_next_page(self) -> None:
        """Append the next batch of rows (up to _PAGE_SIZE) into the list."""
        start = self._rendered_count
        end = min(start + self._PAGE_SIZE, len(self._display_media))
        channel_name = self._creator.get('nickname', '')
        for i in range(start, end):
            row = _ContentRow(self._display_media[i], self._db, self._on_verified_toggled, self, channel_name=channel_name, thumb_pool=self._thumb_pool)
            row.content_type_changed.connect(self._on_content_type_changed)
            self._rows.append(row)
            self._list_layout.addWidget(row)
        self._rendered_count = end
        total = len(self._display_media)
        self._count_label.setText(f'Showing {self._rendered_count} of {total}')
        if self._rendered_count >= total:
            self._load_more_btn.hide()
            self._count_label.setProperty('state', 'done')
            qss_refresh(self._count_label)
        else:
            self._load_more_btn.show()
            remaining = total - self._rendered_count
            self._load_more_btn.setText(f'Load More ({remaining} remaining)')
            self._count_label.setProperty('state', 'more')
            qss_refresh(self._count_label)

    def _load_more(self) -> None:
        """Handle the Load More button click — render the next page."""
        self._list_container.blockSignals(True)
        self._scroll.blockSignals(True)
        self._render_next_page()
        self._list_container.blockSignals(False)
        self._scroll.blockSignals(False)
        self._list_container.updateGeometry()
        self._scroll.updateGeometry()
    def _on_verified_toggled(self) -> None:
        # Sync verified state from rows back to _all_media so _update_last_verified sees it
        media_by_id = {m['content_id']: m for m in self._all_media}
        for row in self._rows:
            cid = row._media.get('content_id', '')
            if cid in media_by_id:
                media_by_id[cid]['is_verified'] = row._media.get('is_verified', 0)
        self._update_last_verified()
        self.verified_changed.emit()
    def _on_verified_check_changed(self, state: int) -> None:
        """Re-render both Stats charts when the verification toggle changes."""
        verified_only = self._verified_check.isChecked()
        if self._creator_timeline is not None:
            self._creator_timeline.set_verified_only(verified_only)
        if self._creator_bar is not None:
            self._creator_bar.set_verified_only(verified_only)

    def _on_stats_type_changed(self, index: int) -> None:
        """Re-render both Stats charts when the content-type combo changes."""
        content_type = self._stats_type_combo.currentData()
        if self._creator_timeline is not None:
            self._creator_timeline.set_content_type(content_type)
        if self._creator_bar is not None:
            self._creator_bar.set_content_type(content_type)

    def _on_stats_range_changed(self, index: int) -> None:
        """Re-render both Stats charts when the time-range combo changes."""
        time_range = self._stats_range_combo.currentData()
        if self._creator_timeline is not None:
            self._creator_timeline.set_time_range(time_range)
        if self._creator_bar is not None:
            self._creator_bar.set_time_range(time_range)

    def _on_copy_report(self) -> None:
        """Generate a per-creator report and copy it to the clipboard."""
        from core.report_generator import generate_report
        from PyQt6.QtWidgets import QApplication
        from ui.dialog_utils import dark_info
        period = self._report_period_combo.currentData() or 'monthly'
        verified_only = self._report_verified_check.isChecked()
        content_type = self._report_type_combo.currentData()
        creator_id = self._creator.get('id')
        report = generate_report(self._db, period=period, verified_only=verified_only,
                                 content_type=content_type, creator_id=creator_id)
        QApplication.clipboard().setText(report)
        dark_info(self, 'Report Copied', 'Creator report has been copied to your clipboard.')

    def _on_export_html(self) -> None:
        """Export a per-creator HTML dashboard page."""
        from core.html_export import generate_html_report
        from PyQt6.QtWidgets import QFileDialog
        from ui.dialog_utils import dark_info, dark_warning
        period = self._report_period_combo.currentData() or 'monthly'
        verified_only = self._report_verified_check.isChecked()
        content_type = self._report_type_combo.currentData()
        time_range = self._stats_range_combo.currentData()
        creator_id = self._creator.get('id')
        try:
            html = generate_html_report(self._db, period=period, verified_only=verified_only,
                                        content_type=content_type, time_range=time_range,
                                        creator_id=creator_id)
            nick = self._creator.get('nickname', 'creator')
            default_name = f'{nick}_dashboard.html'
            path, _ = QFileDialog.getSaveFileName(
                self, 'Export HTML', default_name, 'HTML Files (*.html)')
            if path:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(html)
                dark_info(self, 'Exported', f'HTML dashboard exported to {path}')
        except Exception as exc:
            dark_warning(self, 'Export Failed', str(exc))

    def _on_content_type_changed(self) -> None:
        """Re-render Stats charts and refresh the media list when a content row's type is overridden."""
        # Update _all_media entries from the changed row data
        for row in self._rows:
            content_id = row._media.get('content_id', '')
            for i, m in enumerate(self._all_media):
                if m.get('content_id') == content_id:
                    self._all_media[i] = dict(row._media)
                    break
        # Re-apply filter so the media tab reflects the change immediately
        self._apply_sort_filter()
        # Re-render stats charts
        verified_only = self._verified_check.isChecked()
        content_type = self._stats_type_combo.currentData() if hasattr(self, '_stats_type_combo') else None
        if self._creator_timeline is not None:
            self._creator_timeline.set_verified_only(verified_only)
            self._creator_timeline.set_content_type(content_type)
        if self._creator_bar is not None:
            self._creator_bar.set_verified_only(verified_only)
            self._creator_bar.set_content_type(content_type)
    def _on_refresh_content(self) -> None:
        """Trigger a background API refresh for this creator and reload content when done."""
        if self._on_refresh is not None:
            self._refresh_btn.setEnabled(False)
            self._refresh_btn.setText('Refreshing...')
            self._on_refresh(self._creator['id'])
    def refresh_completed(self) -> None:
        """Called by the parent when a background fetch finishes.\n\nRe-enables the refresh button and reloads content from the database.\nAlso refreshes the Stats tab charts.\n"""
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText('Refresh Content')
        self._load_content()
        self._update_last_verified()
        verified_only = self._verified_check.isChecked()
        content_type = self._stats_type_combo.currentData() if hasattr(self, '_stats_type_combo') else None
        if self._creator_timeline is not None:
            self._creator_timeline.set_verified_only(verified_only)
            self._creator_timeline.set_content_type(content_type)
        if self._creator_bar is not None:
            self._creator_bar.set_verified_only(verified_only)
            self._creator_bar.set_content_type(content_type)
    def _save_notes(self) -> None:
        """Save notes to the database (called by debounce timer)."""
        self._notes_save_label.setText('Saving...')
        text = self._notes_edit.toPlainText()
        self._db.update_creator(self._creator['id'], notes=text)
        self._creator['notes'] = text
        self._notes_save_label.setText('Saved ✓')
        self._notes_save_clear_timer.start()

    def _on_delete_member(self) -> None:
        nick = self._creator.get('nickname', 'Unknown')
        result = dark_question(self, 'Delete Member', f'Are you sure you want to permanently delete {nick} and all associated history data?')
        if result == QMessageBox.StandardButton.Yes:
            creator_id = self._creator['id']
            self._db.delete_creator(creator_id)
            self.member_deleted.emit(creator_id)
            self.accept()
    def refresh_times(self) -> None:
        for row in self._rows:
            row.refresh_time()

    def closeEvent(self, event) -> None:
        """Shut down the thumbnail thread pool when the dialog closes."""
        self._thumb_pool.shutdown(wait=False)
        super().closeEvent(event)

    def _on_export_creator(self) -> None:
        """Export this creator's data to a JSON file."""
        import json as _json
        from PyQt6.QtWidgets import QFileDialog
        from ui.dialog_utils import dark_info, dark_warning
        creator_id = self._creator['id']
        default_name = f"{self._creator.get('nickname', 'creator')}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export Creator', default_name, 'JSON Files (*.json)')
        if not path:
            return
        try:
            data = self._db.export_creator(creator_id)
            with open(path, 'w', encoding='utf-8') as f:
                _json.dump(data, f, indent=2, ensure_ascii=False)
            dark_info(self, 'Exported', f'Creator exported to {path}')
        except Exception as exc:
            dark_warning(self, 'Export Failed', str(exc))