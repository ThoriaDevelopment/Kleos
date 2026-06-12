from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtWidgets import QButtonGroup, QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSplitter, QStackedWidget, QVBoxLayout, QWidget
from core.db_manager import DatabaseManager
from ui.app_icon import create_app_icon
from ui.chart_utils import _ZoomableFigureCanvas
from ui.dialog_utils import enable_window_maximize, handle_fullscreen_keypress
_MPL_STYLE = {'figure.facecolor': '#1A1A1A', 'axes.facecolor': '#222222', 'axes.edgecolor': '#3A3A3A', 'axes.labelcolor': '#E0E0E0', 'xtick.color': '#aaa', 'ytick.color': '#aaa', 'text.color': '#E0E0E0', 'grid.color': '#3A3A3A', 'grid.alpha': 0.5, 'lines.color': '#4A90D9'}
def _apply_style(fig: Figure) -> None:
    fig.patch.set_facecolor(_MPL_STYLE['figure.facecolor'])
    for ax in fig.axes:
        ax.set_facecolor(_MPL_STYLE['axes.facecolor'])
        ax.tick_params(colors=_MPL_STYLE['xtick.color'])
        ax.xaxis.label.set_color(_MPL_STYLE['axes.labelcolor'])
        ax.yaxis.label.set_color(_MPL_STYLE['axes.labelcolor'])
        ax.title.set_color(_MPL_STYLE['text.color'])
        for spine in ax.spines.values():
            spine.set_color(_MPL_STYLE['axes.edgecolor'])
        ax.grid(True, color=_MPL_STYLE['grid.color'], alpha=_MPL_STYLE['grid.alpha'])
class _TimelineChart(_ZoomableFigureCanvas, FigureCanvas):
    """Line chart of view counts for verified content over time.

    Supports scroll-to-zoom, drag-to-pan, and double-click-to-reset.
    """
    def __init__(self, db: DatabaseManager, parent: QWidget | None=None) -> None:
        self._fig = Figure(figsize=(5, 3), dpi=100)
        super().__init__(self._fig)
        self._db = db
        self._pan_active = False
        self._home_xlim = None
        self._home_ylim = None
        self.setParent(parent)
        self.setMinimumHeight(220)
        self._platform = None
        self._verified_only = True
        self._render()
    def set_platform_filter(self, platform: str | None) -> None:
        """Update the platform filter and re-render the chart."""
        self._platform = platform
        self._render()
    def set_verified_only(self, verified_only: bool) -> None:
        """Update the verified-only filter and re-render the chart."""
        self._verified_only = verified_only
        self._render()
    def _render(self) -> None:
        self._fig.clear()
        ax = self._fig.add_subplot(111)
        conditions = ["m.upload_date != ''"]
        params: list[Any] = []
        if self._verified_only:
            conditions.append('m.is_verified = 1')
        if self._platform:
            conditions.append('m.platform = ?')
            params.append(self._platform)
        conditions.append('m.creator_id = c.id')
        where = ' AND '.join(conditions)
        rows = self._db._read(
            f'SELECT m.upload_date, m.view_count, c.nickname, m.platform '
            f'FROM media_content m, creators c '
            f'WHERE {where} ORDER BY m.upload_date ASC',
            tuple(params),
        )
        if not rows:
            label = 'No verified content yet' if self._verified_only else 'No content yet'
            ax.text(0.5, 0.5, label, ha='center', va='center', fontsize=12, color='#888')
            _apply_style(self._fig)
            self.draw()
            self._save_home_limits()
        else:
            by_creator = defaultdict(list)
            for r in rows:
                by_creator[r['nickname']].append((r['upload_date'], r['view_count']))
            colors = ['#4A90D9', '#9B59B6', '#2ECC71', '#E74C3C', '#F39C12', '#1ABC9C', '#E67E22', '#3498DB']
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
            title = 'Verified Content — View Trajectory' if self._verified_only else 'All Content — View Trajectory'
            ax.set_title(title)
            ax.legend(fontsize=8, facecolor='#222222', edgecolor='#3A3A3A', labelcolor='#E0E0E0')
            _apply_style(self._fig)
            self._fig.autofmt_xdate()
            self.draw()
            self._save_home_limits()
class _MonthlyBarChart(_ZoomableFigureCanvas, FigureCanvas):
    """Bar chart of aggregated verified upload counts per month across all creators.

    Supports scroll-to-zoom, drag-to-pan, and double-click-to-reset.
    """
    def __init__(self, db: DatabaseManager, parent: QWidget | None=None) -> None:
        self._fig = Figure(figsize=(5, 3), dpi=100)
        super().__init__(self._fig)
        self._db = db
        self._pan_active = False
        self._home_xlim = None
        self._home_ylim = None
        self.setParent(parent)
        self.setMinimumHeight(220)
        self._platform = None
        self._verified_only = True
        self._render()
    def set_platform_filter(self, platform: str | None) -> None:
        """Update the platform filter and re-render the chart."""
        self._platform = platform
        self._render()
    def set_verified_only(self, verified_only: bool) -> None:
        """Update the verified-only filter and re-render the chart."""
        self._verified_only = verified_only
        self._render()
    def _render(self) -> None:
        self._fig.clear()
        ax = self._fig.add_subplot(111)
        conditions = ["upload_date != ''"]
        params: list[Any] = []
        if self._verified_only:
            conditions.append('is_verified = 1')
        if self._platform:
            conditions.append('platform = ?')
            params.append(self._platform)
        where = ' AND '.join(conditions)
        rows = self._db._read(
            f'SELECT upload_date FROM media_content WHERE {where} ORDER BY upload_date ASC',
            tuple(params),
        )
        if not rows:
            label = 'No verified uploads yet' if self._verified_only else 'No uploads yet'
            ax.text(0.5, 0.5, label, ha='center', va='center', fontsize=12, color='#888')
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
            bar_colors = ['#4A90D9'] * len(months)
            ax.bar(range(len(months)), counts, color=bar_colors, width=0.6, edgecolor='#3A3A3A', linewidth=0.5)
            ax.set_xticks(range(len(months)))
            ax.set_xticklabels(labels, rotation=45, fontsize=8)
            ax.set_ylabel('Uploads')
            title = 'Monthly Verified Upload Activity' if self._verified_only else 'Monthly Upload Activity'
            ax.set_title(title)
            _apply_style(self._fig)
            self._fig.tight_layout()
            self.draw()
            self._save_home_limits()
class AnalyticsWindow(QDialog):
    """Global leaderboard + charts modal, triggered by the crown button."""
    def __init__(self, db: DatabaseManager, parent: QWidget | None=None) -> None:
        super().__init__(parent)
        enable_window_maximize(self)
        self._db = db
        self._filter_platform = None
        self._verified_only = True
        self.setWindowTitle('Analytics & Leaderboard')
        self.setWindowIcon(create_app_icon())
        self.setMinimumSize(860, 580)
        self.resize(960, 680)
        self.setStyleSheet('QDialog { background: #1A1A1A; }QLabel { color: #E0E0E0; }QPushButton { background: #2E2E2E; color: #E0E0E0; border: 1px solid #3A3A3A;   border-radius: 4px; padding: 6px 14px; }QPushButton:hover { background: #4A4A4A; }QPushButton:checked { background: #4A90D9; border-color: #4A90D9; }QListWidget { background: #222222; color: #E0E0E0; border: 1px solid #3A3A3A;   border-radius: 4px; }QListWidget::item:selected { background: #3A3A3A; }QCheckBox { color: #E0E0E0; }QCheckBox::indicator { width: 16px; height: 16px; }')
        self._build_ui()
    def keyPressEvent(self, event) -> None:  # noqa: N802
        if handle_fullscreen_keypress(self, event):
            return
        super().keyPressEvent(event)

    def changeEvent(self, event) -> None:
        """Prevent the parent window from being minimized when this dialog is minimized.

        On Windows, minimizing a QDialog with WindowMinMaxButtonsHint propagates
        the minimize to the parent window.  We detect this and restore only the
        parent, while allowing the dialog to stay minimized normally.
        """
        if event.type() == QEvent.Type.WindowStateChange and self.windowState() & Qt.WindowState.WindowMinimized:
            QTimer.singleShot(0, self._restore_parent_from_minimize)
        super().changeEvent(event)

    def _restore_parent_from_minimize(self) -> None:
        """Restore the parent window that was minimized as a side-effect."""
        parent = self.parent()
        if parent and isinstance(parent, QWidget):
            parent.setWindowState(Qt.WindowState.WindowNoState)
            parent.show()
            parent.raise_()
            parent.activateWindow()
    def _build_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(12, 12, 12, 12)
        vbox.setSpacing(10)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel('Show:'))
        self._btn_all = QPushButton('All')
        self._btn_all.setCheckable(True)
        self._btn_all.setChecked(True)
        self._btn_all.clicked.connect(lambda: self._set_filter(None))
        filter_row.addWidget(self._btn_all)
        self._btn_yt = QPushButton('YouTube')
        self._btn_yt.setCheckable(True)
        self._btn_yt.clicked.connect(lambda: self._set_filter('youtube'))
        filter_row.addWidget(self._btn_yt)
        self._btn_tw = QPushButton('Streamers')
        self._btn_tw.setCheckable(True)
        self._btn_tw.clicked.connect(lambda: self._set_filter('twitch'))
        filter_row.addWidget(self._btn_tw)
        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        self._filter_group.addButton(self._btn_all)
        self._filter_group.addButton(self._btn_yt)
        self._filter_group.addButton(self._btn_tw)
        filter_row.addStretch(1)
        self._verified_check = QCheckBox('Show All Stats')
        self._verified_check.setChecked(False)
        self._verified_check.stateChanged.connect(self._on_verified_changed)
        filter_row.addWidget(self._verified_check)
        vbox.addLayout(filter_row)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel('Leaderboard'))
        self._list = QListWidget()
        left_layout.addWidget(self._list, 1)
        splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
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
        right_layout.addLayout(chart_toggle_row)
        self._chart_stack = QStackedWidget()
        self._timeline = _TimelineChart(self._db)
        self._chart_stack.addWidget(self._timeline)
        self._bar_chart = _MonthlyBarChart(self._db)
        self._chart_stack.addWidget(self._bar_chart)
        right_layout.addWidget(self._chart_stack, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        vbox.addWidget(splitter, 1)
        report_row = QHBoxLayout()
        report_row.addWidget(QLabel('Report:'))
        self._period_combo = QComboBox()
        self._period_combo.addItem('Monthly', 'monthly')
        self._period_combo.addItem('Weekly', 'weekly')
        self._period_combo.addItem('Yearly', 'yearly')
        report_row.addWidget(self._period_combo)
        report_row.addWidget(QLabel('Role:'))
        self._role_combo = QComboBox()
        self._role_combo.addItem('All Roles', None)
        for r in self._db.get_roles():
            self._role_combo.addItem(r['role_name'], r['id'])
        report_row.addWidget(self._role_combo)
        self._report_btn = QPushButton('Copy Report')
        self._report_btn.clicked.connect(self._on_generate_report)
        report_row.addWidget(self._report_btn)
        report_row.addStretch(1)
        vbox.addLayout(report_row)
        close_btn = QPushButton('Close')
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        vbox.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)
        self._load_leaderboard()
    def _set_filter(self, platform: str | None) -> None:
        self._filter_platform = platform
        self._btn_all.setChecked(platform is None)
        self._btn_yt.setChecked(platform == 'youtube')
        self._btn_tw.setChecked(platform == 'twitch')
        self._load_leaderboard()
        self._timeline.set_platform_filter(platform)
        self._bar_chart.set_platform_filter(platform)
    def _on_verified_changed(self, state: int) -> None:
        self._verified_only = state!= Qt.CheckState.Checked.value
        self._timeline.set_verified_only(self._verified_only)
        self._bar_chart.set_verified_only(self._verified_only)
        self._load_leaderboard()
    def _load_leaderboard(self) -> None:
        from ui.components.creator_card import format_subscriber_count
        self._list.clear()
        # Build the ON clause conditions for the LEFT JOIN
        on_conditions = ['m.creator_id = c.id']
        join_params: list[Any] = []
        if self._verified_only:
            on_conditions.append('m.is_verified = 1')
        if self._filter_platform:
            on_conditions.append('m.platform = ?')
            join_params.append(self._filter_platform)
        on_clause = ' AND '.join(on_conditions)
        sql = (
            f'SELECT c.id, c.nickname, COALESCE(SUM(m.view_count), 0) AS total_views '
            f'FROM creators c LEFT JOIN media_content m ON {on_clause} '
            f'GROUP BY c.id ORDER BY total_views DESC'
        )
        rows = self._db._read(sql, tuple(join_params))
        sub_counts = self._db.bulk_subscriber_counts()
        for i, row in enumerate(rows, 1):
            cid = row['id']
            counts = sub_counts.get(cid, {})
            sub_text = format_subscriber_count(counts.get('youtube', 0), counts.get('twitch', 0))
            display = f"{i}. {row['nickname']}  —  {row['total_views']:,} views"
            if sub_text != 'N/A':
                display += f"  |  {sub_text}"
            self._list.addItem(display)

    def _on_generate_report(self) -> None:
        """Generate an analytics report and copy it to the clipboard."""
        from core.report_generator import generate_report
        from PyQt6.QtWidgets import QApplication
        from ui.dialog_utils import dark_info
        period = self._period_combo.currentData() or 'monthly'
        role_id = self._role_combo.currentData()
        report = generate_report(self._db, period=period, role_id=role_id, verified_only=self._verified_only)
        QApplication.clipboard().setText(report)
        dark_info(self, 'Report Copied', 'Analytics report has been copied to your clipboard.')