from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QButtonGroup, QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget
from core.db_manager import DatabaseManager
from ui.app_icon import create_app_icon
from ui.chart_utils import _ZoomableFigureCanvas
from ui.dialog_utils import enable_window_maximize, handle_fullscreen_keypress
from ui.theme.stylesheet import build_dialog_qss
from ui.theme.tokens import C


def _mpl_style() -> dict:
    """Return matplotlib style dict using current theme tokens."""
    return {
        'figure.facecolor': C.DIALOG_BG, 'axes.facecolor': C.INPUT_BG,
        'axes.edgecolor': C.BORDER, 'axes.labelcolor': C.TEXT_PRIMARY,
        'xtick.color': C.TEXT_SECONDARY, 'ytick.color': C.TEXT_SECONDARY,
        'text.color': C.TEXT_PRIMARY, 'grid.color': C.BORDER,
        'grid.alpha': 0.5, 'lines.color': C.ACCENT,
    }


def _apply_style(fig: Figure) -> None:
    s = _mpl_style()
    fig.patch.set_facecolor(s['figure.facecolor'])
    fig.patch.set_edgecolor(s['figure.facecolor'])
    fig.patch.set_linewidth(0)
    for ax in fig.axes:
        ax.set_facecolor(s['axes.facecolor'])
        ax.tick_params(colors=s['xtick.color'])
        ax.xaxis.label.set_color(s['axes.labelcolor'])
        ax.yaxis.label.set_color(s['axes.labelcolor'])
        ax.title.set_color(s['text.color'])
        for spine in ax.spines.values():
            spine.set_color(s['axes.edgecolor'])
        ax.grid(True, color=s['grid.color'], alpha=s['grid.alpha'])


def _chart_title(verified_only: bool, content_type: str | None, base: str) -> str:
    """Build a chart title from filter state.

    Examples:
        verified_only=False, content_type=None → "All Content — View Trajectory"
        verified_only=True,  content_type=None → "Verified Content — View Trajectory"
        verified_only=False, content_type='short'  → "All Shorts — View Trajectory"
        verified_only=True,  content_type='short'  → "Verified Shorts — View Trajectory"
    """
    type_labels: dict[str | None, str] = {
        None:      'Content',
        'short':   'Shorts',
        'video':   'Videos',
        'stream':  'Streams',
    }
    type_part = type_labels.get(content_type, 'Content')
    if content_type is None:
        prefix = 'Verified' if verified_only else 'All'
    else:
        prefix = 'Verified' if verified_only else 'All'
    return f'{prefix} {type_part} — {base}'


class _TimelineChart(_ZoomableFigureCanvas, FigureCanvas):
    """Line chart of view counts over time filtered by verified status, content type and platform.

    Supports scroll-to-zoom, drag-to-pan, and double-click-to-reset.
    """

    def __init__(self, db: DatabaseManager, parent: QWidget | None = None) -> None:
        self._fig = Figure(figsize=(5, 3), dpi=100)
        super().__init__(self._fig)
        self._db = db
        self._pan_active = False
        self._home_xlim = None
        self._home_ylim = None
        self.setParent(parent)
        self.setMinimumHeight(220)
        self.setStyleSheet('background: transparent;')
        self._platform = None
        self._verified_only = False
        self._content_type = None
        self._time_range = None
        self._render()

    def set_platform_filter(self, platform: str | None) -> None:
        """Update the platform filter and re-render the chart."""
        self._platform = platform
        self._render()

    def set_verified_only(self, verified_only: bool) -> None:
        """Update the verified-only filter and re-render the chart."""
        self._verified_only = verified_only
        self._render()

    def set_content_type(self, content_type: str | None) -> None:
        """Update the content-type filter and re-render the chart."""
        self._content_type = content_type
        self._render()

    def set_time_range(self, time_range: str | None) -> None:
        """Update the time-range filter and re-render the chart."""
        self._time_range = time_range
        self._render()

    def _build_conditions(self, table_prefix: str = 'm.') -> tuple[list[str], list[Any]]:
        """Return (conditions_list, params) for the current filters.

        table_prefix: 'm.' for timeline (joins), '' for bar chart (single table).
        """
        p = table_prefix
        conditions: list[str] = [f'{p}upload_date != \'\'']
        params: list[Any] = []
        if self._verified_only:
            conditions.append(f'{p}is_verified = 1')
        ct = self._content_type
        if ct == 'short':
            conditions.append(f'{p}is_short = 1')
        elif ct == 'video':
            conditions.append(f'{p}is_short = 0')
            conditions.append(f'{p}is_stream = 0')
        elif ct == 'stream':
            conditions.append(f'{p}is_stream = 1')
        if self._time_range:
            now = datetime.now(timezone.utc)
            if self._time_range == 'week':
                since = now - timedelta(weeks=1)
            elif self._time_range == 'month':
                since = now - timedelta(days=30)
            elif self._time_range == 'year':
                since = now - timedelta(days=365)
            else:
                since = None
            if since:
                conditions.append(f'{p}upload_date >= ?')
                params.append(since.strftime('%Y-%m-%dT%H:%M:%SZ'))
        if self._platform:
            conditions.append(f'{p}platform = ?')
            params.append(self._platform)
        return conditions, params

    def _render(self) -> None:
        self._fig.clear()
        ax = self._fig.add_subplot(111)
        conditions, params = self._build_conditions(table_prefix='m.')
        conditions.append('m.creator_id = c.id')
        where = ' AND '.join(conditions)
        rows = self._db._read(
            f'SELECT m.upload_date, m.view_count, c.nickname, m.platform '
            f'FROM media_content m, creators c '
            f'WHERE {where} ORDER BY m.upload_date ASC',
            tuple(params),
        )
        if not rows:
            label = _chart_title(self._verified_only, self._content_type, 'View Trajectory')
            ax.text(0.5, 0.5, f'No data for: {label}', ha='center', va='center', fontsize=11, color='#888')
            _apply_style(self._fig)
            self.draw()
            self._save_home_limits()
        else:
            by_creator = defaultdict(list)
            for r in rows:
                by_creator[r['nickname']].append((r['upload_date'], r['view_count']))
            colors = [C.ACCENT, '#9B59B6', '#2ECC71', '#E74C3C', '#F39C12', '#1ABC9C', '#E67E22', '#3498DB']
            for i, (nick, points) in enumerate(by_creator.items()):
                dates = []
                views = []
                for ds, vc in sorted(points, key=lambda p: p[0]):
                    try:
                        dt = datetime.fromisoformat(ds.replace('Z', '+00:00'))
                        dates.append(dt)
                        views.append(vc)
                    except (ValueError, TypeError):
                        pass
                if dates:
                    ax.plot(dates, views, marker='o', markersize=4, label=nick, color=colors[i % len(colors)], linewidth=1.5)
            ax.set_xlabel('Date')
            ax.set_ylabel('Views')
            ax.set_title(_chart_title(self._verified_only, self._content_type, 'View Trajectory'))
            ax.legend(fontsize=8, facecolor=C.INPUT_BG, edgecolor=C.BORDER, labelcolor=C.TEXT_PRIMARY)
            _apply_style(self._fig)
            self._fig.autofmt_xdate()
            self.draw()
            self._save_home_limits()


class _MonthlyBarChart(_ZoomableFigureCanvas, FigureCanvas):
    """Bar chart of aggregated upload counts per month across all creators.

    Supports scroll-to-zoom, drag-to-pan, and double-click-to-reset.
    """

    def __init__(self, db: DatabaseManager, parent: QWidget | None = None) -> None:
        self._fig = Figure(figsize=(5, 3), dpi=100)
        super().__init__(self._fig)
        self._db = db
        self._pan_active = False
        self._home_xlim = None
        self._home_ylim = None
        self.setParent(parent)
        self.setMinimumHeight(220)
        self.setStyleSheet('background: transparent;')
        self._platform = None
        self._verified_only = False
        self._content_type = None
        self._time_range = None
        self._render()

    def set_platform_filter(self, platform: str | None) -> None:
        """Update the platform filter and re-render the chart."""
        self._platform = platform
        self._render()

    def set_verified_only(self, verified_only: bool) -> None:
        """Update the verified-only filter and re-render the chart."""
        self._verified_only = verified_only
        self._render()

    def set_content_type(self, content_type: str | None) -> None:
        """Update the content-type filter and re-render the chart."""
        self._content_type = content_type
        self._render()

    def set_time_range(self, time_range: str | None) -> None:
        """Update the time-range filter and re-render the chart."""
        self._time_range = time_range
        self._render()

    def _build_conditions(self) -> tuple[list[str], list[Any]]:
        """Return (conditions_list, params) for the current filters."""
        conditions: list[str] = ["upload_date != ''"]
        params: list[Any] = []
        if self._verified_only:
            conditions.append('is_verified = 1')
        ct = self._content_type
        if ct == 'short':
            conditions.append('is_short = 1')
        elif ct == 'video':
            conditions.append('is_short = 0')
            conditions.append('is_stream = 0')
        elif ct == 'stream':
            conditions.append('is_stream = 1')
        if self._time_range:
            now = datetime.now(timezone.utc)
            if self._time_range == 'week':
                since = now - timedelta(weeks=1)
            elif self._time_range == 'month':
                since = now - timedelta(days=30)
            elif self._time_range == 'year':
                since = now - timedelta(days=365)
            else:
                since = None
            if since:
                conditions.append('upload_date >= ?')
                params.append(since.strftime('%Y-%m-%dT%H:%M:%SZ'))
        if self._platform:
            conditions.append('platform = ?')
            params.append(self._platform)
        return conditions, params

    def _render(self) -> None:
        self._fig.clear()
        ax = self._fig.add_subplot(111)
        conditions, params = self._build_conditions()
        where = ' AND '.join(conditions)
        rows = self._db._read(
            f'SELECT upload_date FROM media_content WHERE {where} ORDER BY upload_date ASC',
            tuple(params),
        )
        if not rows:
            label = _chart_title(self._verified_only, self._content_type, 'Upload Activity')
            ax.text(0.5, 0.5, f'No data for: {label}', ha='center', va='center', fontsize=11, color='#888')
            _apply_style(self._fig)
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
            bar_colors = [C.ACCENT] * len(months)
            ax.bar(range(len(months)), counts, color=bar_colors, width=0.6, edgecolor=C.BORDER, linewidth=0.5)
            ax.set_xticks(range(len(months)))
            ax.set_xticklabels(labels, rotation=45, fontsize=8)
            ax.set_ylabel('Uploads')
            ax.set_title(_chart_title(self._verified_only, self._content_type, 'Upload Activity'))
            _apply_style(self._fig)
            self._fig.tight_layout()
            self.draw()
            self._save_home_limits()


class AnalyticsWindow(QDialog):
    """Global leaderboard + charts modal, triggered by the crown button."""

    def __init__(self, db: DatabaseManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        enable_window_maximize(self)
        self._db = db
        self._verified_only = False
        self._content_type = None
        self._time_range = None
        self.setWindowTitle('Analytics & Leaderboard')
        self.setWindowIcon(create_app_icon())
        self.setMinimumSize(860, 580)
        self.resize(960, 680)
        self.setStyleSheet(build_dialog_qss())
        self._build_ui()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if handle_fullscreen_keypress(self, event):
            return
        super().keyPressEvent(event)

    def _build_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(12, 12, 12, 12)
        vbox.setSpacing(10)

        # ── Filter row: Verified (left) | Type + Range (right) ──
        filter_row = QHBoxLayout()
        self._verified_check = QCheckBox('Verified only')
        self._verified_check.setChecked(False)
        self._verified_check.stateChanged.connect(self._on_verified_changed)
        filter_row.addWidget(self._verified_check)
        filter_row.addStretch(1)
        filter_row.addWidget(QLabel('Type:'))
        self._content_type_combo = QComboBox()
        self._content_type_combo.addItem('All types', None)
        self._content_type_combo.addItem('Shorts', 'short')
        self._content_type_combo.addItem('Videos', 'video')
        self._content_type_combo.addItem('Streams', 'stream')
        self._content_type_combo.currentIndexChanged.connect(self._on_content_type_changed)
        filter_row.addWidget(self._content_type_combo)
        filter_row.addWidget(QLabel('Range:'))
        self._time_range_combo = QComboBox()
        self._time_range_combo.addItem('All time', None)
        self._time_range_combo.addItem('Last year', 'year')
        self._time_range_combo.addItem('Last month', 'month')
        self._time_range_combo.addItem('Last week', 'week')
        self._time_range_combo.currentIndexChanged.connect(self._on_time_range_changed)
        filter_row.addWidget(self._time_range_combo)
        vbox.addLayout(filter_row)

        # ── Charts ──
        chart_toggle_row = QHBoxLayout()
        chart_toggle_row.addWidget(QLabel('Chart:'))
        self._btn_timeline = QPushButton('Timeline')
        self._btn_timeline.setCheckable(True)
        self._btn_timeline.setChecked(True)
        self._btn_timeline.clicked.connect(lambda: self._chart_stack.setCurrentIndex(0))
        chart_toggle_row.addWidget(self._btn_timeline)
        self._btn_bar = QPushButton('Upload Activity')
        self._btn_bar.setCheckable(True)
        self._btn_bar.clicked.connect(lambda: self._chart_stack.setCurrentIndex(1))
        chart_toggle_row.addWidget(self._btn_bar)
        self._chart_group = QButtonGroup(self)
        self._chart_group.setExclusive(True)
        self._chart_group.addButton(self._btn_timeline)
        self._chart_group.addButton(self._btn_bar)
        chart_toggle_row.addStretch(1)
        vbox.addLayout(chart_toggle_row)
        self._chart_stack = QStackedWidget()
        self._timeline = _TimelineChart(self._db)
        self._chart_stack.addWidget(self._timeline)
        self._bar_chart = _MonthlyBarChart(self._db)
        self._chart_stack.addWidget(self._bar_chart)
        vbox.addWidget(self._chart_stack, 1)

        # ── Report row ──
        report_row = QHBoxLayout()
        report_row.addWidget(QLabel('Report:'))
        self._period_combo = QComboBox()
        self._period_combo.addItem('Monthly', 'monthly')
        self._period_combo.addItem('Weekly', 'weekly')
        self._period_combo.addItem('Yearly', 'yearly')
        self._period_combo.addItem('All time', 'all')
        report_row.addWidget(self._period_combo)
        report_row.addWidget(QLabel('Role:'))
        self._role_combo = QComboBox()
        self._role_combo.addItem('All Roles', None)
        for r in self._db.get_roles():
            self._role_combo.addItem(r['role_name'], r['id'])
        report_row.addWidget(self._role_combo)
        self._report_verified_check = QCheckBox('Verified only')
        self._report_verified_check.setChecked(False)
        report_row.addWidget(self._report_verified_check)
        report_row.addWidget(QLabel('Type:'))
        self._report_type_combo = QComboBox()
        self._report_type_combo.addItem('All types', None)
        self._report_type_combo.addItem('Shorts', 'short')
        self._report_type_combo.addItem('Videos', 'video')
        self._report_type_combo.addItem('Streams', 'stream')
        report_row.addWidget(self._report_type_combo)
        self._report_btn = QPushButton('Copy Report')
        self._report_btn.clicked.connect(self._on_generate_report)
        report_row.addWidget(self._report_btn)
        self._html_btn = QPushButton('Export HTML')
        self._html_btn.clicked.connect(self._on_export_html)
        report_row.addWidget(self._html_btn)
        report_row.addStretch(1)
        vbox.addLayout(report_row)
        close_btn = QPushButton('Close')
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        vbox.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    # ── Filter handlers ──

    def _on_verified_changed(self, state: int) -> None:
        self._verified_only = state == Qt.CheckState.Checked.value
        self._timeline.set_verified_only(self._verified_only)
        self._bar_chart.set_verified_only(self._verified_only)

    def _on_content_type_changed(self, index: int) -> None:
        self._content_type = self._content_type_combo.currentData()
        self._timeline.set_content_type(self._content_type)
        self._bar_chart.set_content_type(self._content_type)

    def _on_time_range_changed(self, index: int) -> None:
        self._time_range = self._time_range_combo.currentData()
        self._timeline.set_time_range(self._time_range)
        self._bar_chart.set_time_range(self._time_range)

    def _on_generate_report(self) -> None:
        """Generate an analytics report and copy it to the clipboard."""
        from core.report_generator import generate_report
        from PyQt6.QtWidgets import QApplication
        from ui.dialog_utils import dark_info
        period = self._period_combo.currentData() or 'monthly'
        role_id = self._role_combo.currentData()
        verified_only = self._report_verified_check.isChecked()
        content_type = self._report_type_combo.currentData()
        report = generate_report(self._db, period=period, role_id=role_id, verified_only=verified_only, content_type=content_type)
        QApplication.clipboard().setText(report)
        dark_info(self, 'Report Copied', 'Analytics report has been copied to your clipboard.')

    def _on_export_html(self) -> None:
        """Export an HTML community dashboard page."""
        from core.html_export import generate_html_report
        from PyQt6.QtWidgets import QFileDialog
        from ui.dialog_utils import dark_info, dark_warning
        period = self._period_combo.currentData() or 'monthly'
        role_id = self._role_combo.currentData()
        verified_only = self._report_verified_check.isChecked()
        content_type = self._report_type_combo.currentData()
        time_range = self._time_range_combo.currentData()
        try:
            html = generate_html_report(self._db, period=period, role_id=role_id, verified_only=verified_only, content_type=content_type, time_range=time_range)
            default_name = f'{self._db.profile}_dashboard.html'
            path, _ = QFileDialog.getSaveFileName(
                self, 'Export HTML', default_name, 'HTML Files (*.html)')
            if path:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(html)
                dark_info(self, 'Exported', f'HTML dashboard exported to {path}')
        except Exception as exc:
            dark_warning(self, 'Export Failed', str(exc))