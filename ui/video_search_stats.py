"""Video-search stats dialog — the "leaderboard" panel for a set of
discovered videos.

Mirrors the per-creator Stats tab in ``ui/components/history_dialog.py``
(``_CreatorTimelineChart`` + ``_CreatorBarChart``), but fed from an in-memory
list of video-search results instead of the ``media_content`` table.  The two
charts use only data the search already fetched (view counts, upload dates,
short/stream flags), so opening this dialog costs **0 YouTube API units**.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.dates import date2num
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from core.db_manager import DatabaseManager
from ui.app_icon import create_app_icon
from ui.chart_common import apply_style, smooth_mpl_patch
from ui.chart_utils import _ZoomableFigureCanvas
from ui.geometry import restore_geometry, save_geometry
from ui.theme import C
from ui.theme.stylesheet import build_dialog_qss


def _parse_date(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None


def _since_for_range(time_range: str | None) -> datetime | None:
    """Mirror chart_common.build_conditions's time-range window (UTC)."""
    if not time_range:
        return None
    now = datetime.now(timezone.utc)
    if time_range == 'week':
        return now - timedelta(weeks=1)
    if time_range == 'month':
        return now - timedelta(days=30)
    if time_range == 'year':
        return now - timedelta(days=365)
    return None


def _filter_videos(videos: list[dict[str, Any]], content_type: str | None,
                   time_range: str | None) -> list[dict[str, Any]]:
    """Client-side filter of the in-memory video list, mirroring the roster
    charts' Type + Range filters (no DB, no API)."""
    since = _since_for_range(time_range)
    out: list[dict[str, Any]] = []
    for v in videos:
        if content_type == 'short' and not v.get('is_short'):
            continue
        if content_type == 'video' and (v.get('is_short') or v.get('is_stream')):
            continue
        if content_type == 'stream' and not v.get('is_stream'):
            continue
        if since is not None:
            dt = _parse_date(v.get('upload_date', ''))
            if dt is None or dt < since:
                continue
        out.append(v)
    return out


class _VideoTimelineChart(_ZoomableFigureCanvas, FigureCanvas):
    """View-count trajectory over time for a set of discovered videos.

    Each video contributes one point at its upload date with its current
    view count — the same shape as the per-creator timeline, treating the
    whole result set as one community's uploads.
    """

    def __init__(self, videos: list[dict[str, Any]], parent: QWidget | None = None) -> None:
        self._fig = Figure(figsize=(5, 2.5), dpi=100)
        super().__init__(self._fig)
        self._videos = videos
        self._content_type: str | None = None
        self._time_range: str | None = None
        self._pan_active = False
        self._home_xlim = None
        self._home_ylim = None
        self.setParent(parent)
        self.setMinimumHeight(220)
        self.setStyleSheet('background: transparent;')
        self._render()

    def set_content_type(self, content_type: str | None) -> None:
        self._content_type = content_type
        self._render()

    def set_time_range(self, time_range: str | None) -> None:
        self._time_range = time_range
        self._render()

    def _render(self) -> None:
        self._fig.clear()
        ax = self._fig.add_subplot(111)
        videos = _filter_videos(self._videos, self._content_type, self._time_range)
        if not videos:
            ax.text(0.5, 0.5, 'No videos in this range', ha='center', va='center',
                    fontsize=12, color='#888')
            apply_style(self._fig)
            self.draw()
            self._save_home_limits()
            return
        points: list[tuple[datetime, int]] = []
        for v in videos:
            dt = _parse_date(v.get('upload_date', ''))
            if dt is None:
                continue
            points.append((dt, int(v.get('view_count', 0) or 0)))
        points.sort(key=lambda p: p[0])
        if not points:
            ax.text(0.5, 0.5, 'No parseable dates', ha='center', va='center',
                    fontsize=12, color='#888')
            apply_style(self._fig)
            self.draw()
            self._save_home_limits()
            return
        dates = [p[0] for p in points]
        views = [p[1] for p in points]
        patch = smooth_mpl_patch(date2num(dates), views, C.ACCENT,
                                 floor=0.0, linewidth=1.5, zorder=3)
        if patch is not None:
            ax.add_patch(patch)
        ax.scatter(dates, views, marker='o', s=16, color=C.ACCENT, zorder=4)
        ax.set_xlabel('Upload date')
        ax.set_ylabel('Views')
        ax.set_title('View Trajectory')
        apply_style(self._fig)
        self._fig.autofmt_xdate()
        self.draw()
        self._save_home_limits()


class _VideoBarChart(_ZoomableFigureCanvas, FigureCanvas):
    """Upload-activity bar chart for a set of discovered videos.

    Buckets by day when the result span is short (≤ ~2 weeks) so a
    last-week / last-day search shows useful granularity, otherwise by month.
    """

    def __init__(self, videos: list[dict[str, Any]], parent: QWidget | None = None) -> None:
        self._fig = Figure(figsize=(5, 2.5), dpi=100)
        super().__init__(self._fig)
        self._videos = videos
        self._content_type: str | None = None
        self._time_range: str | None = None
        self._pan_active = False
        self._home_xlim = None
        self._home_ylim = None
        self.setParent(parent)
        self.setMinimumHeight(220)
        self.setStyleSheet('background: transparent;')
        self._render()

    def set_content_type(self, content_type: str | None) -> None:
        self._content_type = content_type
        self._render()

    def set_time_range(self, time_range: str | None) -> None:
        self._time_range = time_range
        self._render()

    def _render(self) -> None:
        self._fig.clear()
        ax = self._fig.add_subplot(111)
        videos = _filter_videos(self._videos, self._content_type, self._time_range)
        if not videos:
            ax.text(0.5, 0.5, 'No videos in this range', ha='center', va='center',
                    fontsize=12, color='#888')
            apply_style(self._fig)
            self.draw()
            self._save_home_limits()
            return
        # Decide bucket granularity from the span of the (filtered) dates.
        parsed: list[datetime] = []
        for v in videos:
            dt = _parse_date(v.get('upload_date', ''))
            if dt is not None:
                parsed.append(dt)
        if not parsed:
            ax.text(0.5, 0.5, 'No parseable dates', ha='center', va='center',
                    fontsize=12, color='#888')
            apply_style(self._fig)
            self.draw()
            self._save_home_limits()
            return
        span_days = (max(parsed) - min(parsed)).days
        daily = span_days <= 14

        counts: dict[str, int] = defaultdict(int)
        for dt in parsed:
            key = dt.strftime('%Y-%m-%d') if daily else dt.strftime('%Y-%m')
            counts[key] += 1
        keys = sorted(counts.keys())
        values = [counts[k] for k in keys]
        labels = []
        for k in keys:
            try:
                fmt = '%d %b' if daily else '%b %y'
                labels.append(datetime.strptime(k, '%Y-%m-%d' if daily else '%Y-%m').strftime(fmt))
            except ValueError:
                labels.append(k)
        ax.bar(range(len(keys)), values, color=C.ACCENT, width=0.6,
               edgecolor=C.BORDER, linewidth=0.5)
        ax.set_xticks(range(len(keys)))
        ax.set_xticklabels(labels, rotation=45, fontsize=8)
        ax.set_ylabel('Uploads')
        ax.set_title('Upload Activity')
        apply_style(self._fig)
        self._fig.tight_layout()
        self.draw()
        self._save_home_limits()


class VideoSearchStatsDialog(QDialog):
    """Stats panel for a video-search result set — two charts mirroring the
    roster's per-creator "Media History" Stats tab (Type + Range filters,
    Timeline / Upload Activity toggle), fed from the in-memory results.
    """

    def __init__(self, videos: list[dict[str, Any]], db: DatabaseManager,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._videos = videos
        self._db = db
        self.setWindowTitle('Video Search — Stats')
        self.setWindowIcon(create_app_icon())
        self.setMinimumSize(640, 460)
        self.resize(760, 560)
        self.setStyleSheet(build_dialog_qss())
        restore_geometry(self, 'VideoSearchStatsDialog', self._db)
        self.finished.connect(lambda _r: save_geometry(self, 'VideoSearchStatsDialog', self._db))
        self._timeline: _VideoTimelineChart | None = None
        self._bar: _VideoBarChart | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(12, 10, 12, 10)
        vbox.setSpacing(8)

        title = QLabel('Community Video Stats')
        title.setObjectName('dialogTitle')
        vbox.addWidget(title)
        hint = QLabel(
            f'{len(self._videos)} video(s) from the current search. '
            'Charts use the data already fetched — no extra YouTube quota.'
        )
        hint.setObjectName('hintLabel')
        hint.setWordWrap(True)
        vbox.addWidget(hint)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel('Type:'))
        self._type_combo = QComboBox()
        self._type_combo.addItem('All types', None)
        self._type_combo.addItem('Shorts', 'short')
        self._type_combo.addItem('Videos', 'video')
        self._type_combo.addItem('Streams', 'stream')
        self._type_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self._type_combo)
        filter_row.addWidget(QLabel('Range:'))
        self._range_combo = QComboBox()
        self._range_combo.addItem('All time', None)
        self._range_combo.addItem('Last year', 'year')
        self._range_combo.addItem('Last month', 'month')
        self._range_combo.addItem('Last week', 'week')
        self._range_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self._range_combo)
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
        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(self._btn_timeline)
        group.addButton(self._btn_bar)
        vbox.addLayout(filter_row)

        self._chart_stack = QStackedWidget()
        self._chart_stack.addWidget(QWidget())  # placeholder for timeline
        self._chart_stack.addWidget(QWidget())  # placeholder for bar
        vbox.addWidget(self._chart_stack, 1)

        self._build_charts()

        close = QPushButton('Close')
        close.setFixedWidth(100)
        close.clicked.connect(self.accept)
        vbox.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)

    def _build_charts(self) -> None:
        content_type = self._type_combo.currentData()
        self._timeline = _VideoTimelineChart(self._videos)
        self._timeline.set_content_type(content_type)
        self._chart_stack.removeWidget(self._chart_stack.widget(0))
        self._chart_stack.insertWidget(0, self._timeline)
        self._bar = _VideoBarChart(self._videos)
        self._bar.set_content_type(content_type)
        self._chart_stack.removeWidget(self._chart_stack.widget(1))
        self._chart_stack.insertWidget(1, self._bar)
        self._chart_stack.setCurrentIndex(0 if self._btn_timeline.isChecked() else 1)

    def _on_filter_changed(self) -> None:
        content_type = self._type_combo.currentData()
        time_range = self._range_combo.currentData()
        if self._timeline is not None:
            self._timeline.set_content_type(content_type)
            self._timeline.set_time_range(time_range)
        if self._bar is not None:
            self._bar.set_content_type(content_type)
            self._bar.set_time_range(time_range)