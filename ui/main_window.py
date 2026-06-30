from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Any
from ui.theme import C, M
from ui.theme.stylesheet import build_dialog_qss, build_main_window_qss, refresh_all_styles
from ui.theme.tokens import theme_manager, THEME_NAMES
from ui.geometry import save_geometry, restore_geometry
from ui.command_palette import CommandPalette, Action
from PyQt6 import sip
from PyQt6.QtCore import QAbstractAnimation, QDate, QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QLinearGradient, QPainter, QShortcut
from PyQt6.QtWidgets import QCalendarWidget, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QProgressBar, QScrollArea, QStackedWidget, QTextEdit, QVBoxLayout, QWidget
from core.api_client import FetchWorker, load_api_keys
from core.db_manager import DatabaseManager
from core.keyword_verify import KeywordVerifyWorker
from core.verify_worker import ANTHROPIC_AVAILABLE, GEMINI_AVAILABLE, VerifyWorker
from ui.verify_dialog import VerifyDialog, VerifyResult
logger = logging.getLogger(__name__)
from ui.app_icon import create_app_icon
from ui.components.creator_card import CreatorCard, format_subscriber_count
from ui.components.history_dialog import HistoryDialog
from ui.dialog_utils import dark_question, dark_warning, dark_info, handle_fullscreen_keypress
from ui.settings_dialog import SettingsDialog
from ui.analytics_window import AnalyticsWindow
from ui.notification import NotificationToast
class GradientCanvasV2(QWidget):
    """Full-window underlay widget that paints a slow-breathing gradient\nusing design-system colour tokens.\n\nThe gradient alternates between C.BG_BASE and C.BG_DEEP at ±4% opacity\nover a 10-second sinusoidal loop driven by QVariantAnimation.\nNo layout geometry is recalculated — only a paint event fires.\n"""
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._breathe = 0.0
        self._col_a = QColor(C.BG_BASE)
        self._col_b = QColor(C.BG_DEEP)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(5000)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.valueChanged.connect(self._on_value)
        self._anim.finished.connect(self._ping_pong)
        self._going_forward = True
        self._anim.start()
    def _ping_pong(self) -> None:
        """Reverse direction and restart for an infinite sine loop."""
        self._going_forward = not self._going_forward
        if self._going_forward:
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
        else:
            self._anim.setStartValue(1.0)
            self._anim.setEndValue(0.0)
        self._anim.start()
    def _on_value(self, val: float) -> None:
        self._breathe = val
        self.update()
    def showEvent(self, event) -> None:
        """Resume breathing animation when the window becomes visible."""
        super().showEvent(event)
        state = self._anim.state()
        if state == QAbstractAnimation.State.Paused:
            self._anim.resume()
        elif state == QAbstractAnimation.State.Stopped:
            self._anim.start()
    def hideEvent(self, event) -> None:
        """Pause breathing animation when the window is hidden or minimized."""
        super().hideEvent(event)
        if self._anim.state() == QAbstractAnimation.State.Running:
            self._anim.pause()
    def resizeEvent(self, event) -> None:
        self.resize(self.parent().size())
        super().resizeEvent(event)
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        t = self._breathe
        r = int(self._col_a.red() + (self._col_b.red() - self._col_a.red()) * t)
        g = int(self._col_a.green() + (self._col_b.green() - self._col_a.green()) * t)
        b = int(self._col_a.blue() + (self._col_b.blue() - self._col_a.blue()) * t)
        top_color = QColor(r, g, b)
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, top_color)
        grad.setColorAt(1.0, QColor(C.BG_DEEP))
        painter.fillRect(self.rect(), grad)

    def refresh_colors(self) -> None:
        """Update gradient colours after a theme change and repaint."""
        self._col_a = QColor(C.BG_BASE)
        self._col_b = QColor(C.BG_DEEP)
        self.update()
class _InlineEditDialog(QDialog):
    _CALENDAR_QSS = None  # Built dynamically in __init__ for theme support

    def __init__(self, field: str, current_value: str, parent: QWidget | None=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f'Edit {field.replace('_', ' ').title()}')
        self.setMinimumWidth(320)
        self._CALENDAR_QSS = (
            f'QCalendarWidget {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; }}'
            f'QCalendarWidget QToolButton {{ color: {C.TEXT_PRIMARY}; background: {C.INPUT_BG}; border: 1px solid {C.INPUT_BORDER}; }}'
            f'QCalendarWidget QMenu {{ background: {C.BORDER}; color: {C.TEXT_PRIMARY}; }}'
            f'QCalendarWidget QAbstractItemView {{ background: {C.INPUT_BG}; selection-background-color: {C.TEXT_PRIMARY}; border: none; padding: 4px; }}'
            f'#qt_calendar_yearbutton:hover {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; }}'
            f'#qt_calendar_yearedit {{ color: {C.TEXT_PRIMARY}; }}'
            f'#qt_calendar_prevmonth {{ background: {C.INPUT_BG}; border: none; }}'
            f'#qt_calendar_nextmonth {{ background: {C.INPUT_BG}; border: none; }}'
            f'QCalendarWidget QTableView {{ background: {C.BORDER}; gridline-color: {C.ACCENT}; selection-color: {C.TEXT_ON_ACCENT}; alternate-background-color: {C.BG_BASE}; }}'
        )
        self.setStyleSheet(
            f'QDialog {{ background: {C.BG_DEEP}; }}'
            f'QLabel {{ color: {C.TEXT_PRIMARY}; background: transparent; }}'
            f'QLineEdit {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.INPUT_BORDER}; border-radius: 4px; padding: 4px 8px; }}'
            f'QListWidget {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.INPUT_BORDER}; border-radius: 4px; }}'
            f'QListWidget::item:selected {{ background: {C.BG_HOVER}; }}'
            f'QCheckBox {{ color: {C.TEXT_PRIMARY}; border: 1px solid {C.CHECK_ACCENT}; }}'
            f'QPushButton {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; border-radius: 4px; padding: 6px 14px; }}'
            f'QPushButton:hover {{ background: {C.BG_HOVER}; }}'
            f'QDialogButtonBox {{ background: transparent; }}'
        )
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._field = field
        self._plat_list = None
        self._calendar = None
        self._edit = None
        if field == 'date_added':
            self._calendar = QCalendarWidget()
            self._calendar.setStyleSheet(self._CALENDAR_QSS)
            self._calendar.setGridVisible(True)
            self._calendar.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.ShortDayNames)
            try:
                dt = datetime.fromisoformat(current_value.replace('Z', '+00:00'))
                self._calendar.setSelectedDate(QDate(dt.year, dt.month, dt.day))
            except (ValueError, TypeError):
                self._calendar.setSelectedDate(QDate.currentDate())
            form.addRow('Date Added:', self._calendar)
        else:
            self._edit = QLineEdit(current_value)
            form.addRow(f'{field.replace('_', ' ').title()}:', self._edit)
            if field == 'platforms':
                self._edit.setVisible(False)
                self._plat_list = QListWidget()
                self._plat_list.setMaximumHeight(80)
                for p in ['youtube', 'twitch']:
                    item = QListWidgetItem(p)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if p in json.loads(current_value) else Qt.CheckState.Unchecked)
                    self._plat_list.addItem(item)
                form.addRow('Platforms:', self._plat_list)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    def value(self) -> str:
        if self._calendar is not None:
            d = self._calendar.selectedDate()
            return f'{d.year():04d}-{d.month():02d}-{d.day():02d}T00:00:00Z'
        else:
            if self._plat_list is not None:
                selected = []
                for i in range(self._plat_list.count()):
                    item = self._plat_list.item(i)
                    if item.checkState() == Qt.CheckState.Checked:
                        selected.append(item.text())
                return json.dumps(selected)
            else:
                return self._edit.text().strip()
class _MissingKeysBanner(QWidget):
    configure_requested = pyqtSignal()
    def __init__(self, parent: QWidget | None=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        label = QLabel('API keys missing. Please configure them in Settings to pull media data.')
        label.setStyleSheet(f'font-size: 14px; color: {C.DANGER}; background: transparent;')
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        btn = QPushButton('Open Settings')
        btn.setFixedWidth(140)
        btn.clicked.connect(self.configure_requested.emit)
        layout.addWidget(btn)
class _AddCreatorDialog(QDialog):
    """Dialog for adding a new media member."""
    def __init__(self, db: DatabaseManager, parent: QWidget | None=None) -> None:
        super().__init__(parent)
        self._db = db
        self.setWindowTitle('Add Media Member')
        self.setMinimumWidth(380)
        self.setStyleSheet(
            f'QDialog {{ background: {C.BG_DEEP}; }}'
            f'QLabel {{ color: {C.TEXT_PRIMARY}; background: transparent; }}'
            f'QLineEdit {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.INPUT_BORDER}; border-radius: 4px; padding: 4px 8px; }}'
            f'QLineEdit::placeholder {{ color: {C.INPUT_PLACEHOLDER}; }}'
            f'QComboBox {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.INPUT_BORDER}; border-radius: 4px; padding: 4px 8px; }}'
            f'QComboBox QAbstractItemView {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.INPUT_BORDER}; selection-background-color: {C.BG_HOVER}; }}'
            f'QListWidget {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.CHECK_ACCENT}; }}'
            f'QPushButton {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; border-radius: 4px; padding: 6px 14px; }}'
            f'QPushButton:hover {{ background: {C.BG_HOVER}; }}'
            f'QDialogButtonBox {{ background: transparent; }}'
        )
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._nick = QLineEdit()
        form.addRow('Nickname:', self._nick)
        self._youtube_check = QCheckBox('youtube')
        self._twitch_check = QCheckBox('twitch')
        plat_container = QWidget()
        plat_layout = QVBoxLayout(plat_container)
        plat_layout.setContentsMargins(4, 4, 4, 4)
        plat_layout.setSpacing(2)
        plat_layout.addWidget(self._youtube_check)
        plat_layout.addWidget(self._twitch_check)
        plat_container.setStyleSheet(f'QWidget {{ background: {C.INPUT_BG}; border: 1px solid {C.INPUT_BORDER}; border-radius: 4px; }}QCheckBox {{ outline: none; }}QCheckBox::focus {{ outline: none; }}')
        form.addRow('Platforms:', plat_container)
        self._youtube_link = QLineEdit()
        self._youtube_link.setPlaceholderText('https://www.youtube.com/channel/...')
        self._twitch_link = QLineEdit()
        self._twitch_link.setPlaceholderText('https://www.twitch.tv/...')
        self._youtube_link_stack = QStackedWidget()
        self._youtube_link_stack.setMinimumHeight(32)
        self._youtube_link_placeholder = QWidget()
        self._youtube_link_stack.addWidget(self._youtube_link_placeholder)
        self._youtube_link_stack.addWidget(self._youtube_link)
        self._youtube_link_stack.setCurrentIndex(0)
        form.addRow('YouTube Channel Link:', self._youtube_link_stack)
        self._twitch_link_stack = QStackedWidget()
        self._twitch_link_stack.setMinimumHeight(32)
        self._twitch_link_placeholder = QWidget()
        self._twitch_link_stack.addWidget(self._twitch_link_placeholder)
        self._twitch_link_stack.addWidget(self._twitch_link)
        self._twitch_link_stack.setCurrentIndex(0)
        form.addRow('Twitch Channel Link:', self._twitch_link_stack)
        self._youtube_check.stateChanged.connect(self._on_youtube_toggled)
        self._twitch_check.stateChanged.connect(self._on_twitch_toggled)
        self._role_combo = QComboBox()
        for r in db.get_roles():
            self._role_combo.addItem(r['role_name'], r['id'])
        form.addRow('Role:', self._role_combo)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    def _on_youtube_toggled(self, state: int) -> None:
        checked = state == Qt.CheckState.Checked.value
        self._youtube_link_stack.setCurrentIndex(1 if checked else 0)
        if not checked:
            self._youtube_link.clear()
    def _on_twitch_toggled(self, state: int) -> None:
        checked = state == Qt.CheckState.Checked.value
        self._twitch_link_stack.setCurrentIndex(1 if checked else 0)
        if not checked:
            self._twitch_link.clear()
    def values(self) -> tuple[str, list[str], int, str | None, str | None] | None:
        nick = self._nick.text().strip()
        if not nick:
            return None
        else:
            platforms = []
            if self._youtube_check.isChecked():
                platforms.append('youtube')
            if self._twitch_check.isChecked():
                platforms.append('twitch')
            role_id = self._role_combo.currentData()
            if role_id is None:
                return None
            else:
                youtube_link = self._youtube_link.text().strip() or None
                twitch_link = self._twitch_link.text().strip() or None
                return (nick, platforms, role_id, youtube_link, twitch_link)
class MainWindow(QMainWindow):
    """Central dashboard with top bar controls and a grid of CreatorCards."""
    def __init__(self, db: DatabaseManager, parent: QWidget | None=None) -> None:
        super().__init__(parent)
        self._db = db
        self._cards = {}
        self._pending_card_data = []
        self._batch_timer = QTimer(self)
        self._batch_timer.setSingleShot(True)
        self._batch_timer.timeout.connect(self._create_next_batch)
        self._fetch_worker = None
        self._verify_worker = None
        self._keyword_worker = None
        self._active_history = None
        self._active_filter_role_id = None
        self._data_fetched = False
        self._search_text = ''
        self._sort_key = 'date_added'
        self._cascade_timers = []
        self._pending_close = False
        self._cooldown_timer = QTimer(self)
        self._cooldown_timer.setInterval(1000)
        self._cooldown_timer.timeout.connect(self._cooldown_tick)
        self._cooldown_remaining = 0
        self._pending_profile = None
        self._pending_import = None
        self.setWindowTitle('Kleos — Media Dashboard')
        self.setWindowIcon(create_app_icon())
        self.setMinimumSize(800, 520)
        self.resize(960, 640)
        self.setAcceptDrops(True)
        self._build_ui()
        # Keyboard shortcuts
        QShortcut(QKeySequence('Ctrl+R'), self, activated=self._on_refresh_all)
        QShortcut(QKeySequence('Ctrl+N'), self, activated=self._on_add_creator)
        QShortcut(QKeySequence('Ctrl+F'), self, activated=self._focus_search)
        QShortcut(QKeySequence('Ctrl+K'), self, activated=self._open_command_palette)
        # Restore the main-window geometry from the global settings file so the
        # size/position survives a profile switch (per-profile dialogs are
        # restored by each dialog individually).
        restore_geometry(self, 'MainWindow', self._db, global_store=True)
        self.apply_main_window_qss()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_relative_times)
        self._timer.start(60000)
        self._refresh_cards()
        theme_manager.theme_changed.connect(self._on_theme_changed)
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName('centralWidget')
        self.setCentralWidget(central)
        self._bg_canvas = GradientCanvasV2(central)
        self._bg_canvas.lower()
        self._bg_canvas.resize(central.size())
        central.resizeEvent = self._on_central_resize
        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        top_row1 = QHBoxLayout()
        top_row1.setContentsMargins(16, 8, 16, 2)
        add_btn = QPushButton('+ Add Media Member')
        add_btn.setToolTip('Add a new media member (Ctrl+N)')
        add_btn.clicked.connect(self._on_add_creator)
        top_row1.addWidget(add_btn)
        top_row1.addSpacing(8)
        self._refresh_all_btn = QPushButton('⟳ Refresh All')
        self._refresh_all_btn.setToolTip('Refresh all member data from APIs (Ctrl+R)')
        self._refresh_all_btn._original_text = '⟳ Refresh All'
        self._refresh_all_btn.clicked.connect(self._on_refresh_all)
        top_row1.addWidget(self._refresh_all_btn)
        top_row1.addStretch(1)
        self._verify_btn = QPushButton('✓ Verify')
        self._verify_btn.setToolTip('Verify media using keywords or AI')
        self._verify_btn.clicked.connect(self._on_verify)
        top_row1.addWidget(self._verify_btn)
        top_row1.addSpacing(8)
        settings_btn = QPushButton('⚙ Settings')
        settings_btn.setToolTip('Open settings (API keys, profiles, roles)')
        settings_btn.clicked.connect(self._on_settings)
        top_row1.addWidget(settings_btn)
        top_row1.addSpacing(8)
        leaderboard_btn = QPushButton('♛ Leaderboard')
        leaderboard_btn.setToolTip('View analytics and leaderboard')
        leaderboard_btn.clicked.connect(self._on_leaderboard)
        top_row1.addWidget(leaderboard_btn)
        top_row2 = QHBoxLayout()
        top_row2.setContentsMargins(16, 2, 16, 8)
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText('Search members…')
        self._search_edit.setToolTip('Search members by name (Ctrl+F)')
        self._search_edit.setFixedWidth(180)
        self._search_edit.textChanged.connect(self._on_search_changed)
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(200)
        self._search_debounce.timeout.connect(self._apply_filter)
        top_row2.addWidget(self._search_edit)
        top_row2.addSpacing(8)
        self._fetch_status = QLabel('')
        self._fetch_status.setObjectName('fetchStatus')
        self._fetch_status.setVisible(False)
        top_row2.addWidget(self._fetch_status)
        top_row2.addStretch(1)
        top_row2.addWidget(QLabel('Sort: '))
        self._sort_combo = QComboBox()
        self._sort_combo.setToolTip('Sort members by date, name, or subscribers')
        self._sort_combo.addItem('Date Added', 'date_added')
        self._sort_combo.addItem('Name', 'name')
        self._sort_combo.addItem('Subscribers', 'subscribers')
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        top_row2.addWidget(self._sort_combo)
        top_row2.addSpacing(8)
        top_row2.addWidget(QLabel('Filter: '))
        self._filter_combo = QComboBox()
        self._filter_combo.setToolTip('Filter members by role')
        self._refresh_filter_combo()
        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        top_row2.addWidget(self._filter_combo)
        top_row2.addSpacing(8)
        top_row2.addWidget(QLabel('Profile: '))
        self._profile_combo = QComboBox()
        self._profile_combo.setToolTip('Switch active profile')
        self._refresh_profile_combo()
        self._profile_combo.currentIndexChanged.connect(self._on_profile_switch)
        top_row2.addWidget(self._profile_combo)
        top_container = QWidget()
        top_container.setObjectName('topBar')
        self._top_container = top_container
        top_vbox = QVBoxLayout(top_container)
        top_vbox.setContentsMargins(0, 0, 0, 0)
        top_vbox.setSpacing(0)
        top_vbox.addLayout(top_row1)
        top_vbox.addLayout(top_row2)
        vbox.addWidget(top_container)
        # Progress bar area for auto-verify (hidden by default)
        self._verify_progress_area = QWidget()
        self._verify_progress_area.setVisible(False)
        progress_layout = QHBoxLayout(self._verify_progress_area)
        progress_layout.setContentsMargins(16, 6, 16, 6)
        self._verify_progress_label = QLabel('')
        self._verify_progress_label.setObjectName('verifyProgress')
        progress_layout.addWidget(self._verify_progress_label)
        self._verify_progress_bar = QProgressBar()
        self._verify_progress_bar.setMinimum(0)
        self._verify_progress_bar.setMaximum(100)
        self._verify_progress_bar.setTextVisible(False)
        self._verify_progress_bar.setFixedHeight(18)
        progress_layout.addWidget(self._verify_progress_bar, 1)
        self._verify_cancel_btn = QPushButton('Cancel')
        self._verify_cancel_btn.setFixedWidth(80)
        self._verify_cancel_btn.clicked.connect(self._on_verify_cancel)
        progress_layout.addWidget(self._verify_cancel_btn)
        vbox.addWidget(self._verify_progress_area)
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setObjectName('separator')
        self._separator = sep
        vbox.addWidget(sep)
        self._stack = QVBoxLayout()
        self._stack.setContentsMargins(16, 12, 16, 12)
        self._stack.setSpacing(8)
        self._banner = _MissingKeysBanner()
        self._banner.configure_requested.connect(self._on_settings)
        self._banner.setVisible(False)
        self._stack.addWidget(self._banner)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.viewport().setStyleSheet('background: transparent;')
        self._card_container = QWidget()
        self._card_container.setStyleSheet('background: transparent;')
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._card_layout.setSpacing(6)
        self._card_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinAndMaxSize)
        self._scroll.setWidget(self._card_container)
        self._stack.addWidget(self._scroll, 1)
        # Empty state widget (shown when no creators exist)
        self._empty_state = QWidget()
        empty_layout = QVBoxLayout(self._empty_state)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(12)
        empty_icon = QLabel('🎬')
        empty_icon.setObjectName('emptyStateIcon')
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_icon)
        self._empty_title = QLabel('No media members yet')
        self._empty_title.setObjectName('emptyTitle')
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._empty_title)
        self._empty_desc = QLabel('Add your first media member to get started.')
        self._empty_desc.setObjectName('emptyDesc')
        self._empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._empty_desc)
        self._empty_btn = QPushButton('+ Add Media Member')
        self._empty_btn.setFixedWidth(200)
        self._empty_btn.setObjectName('emptyBtn')
        self._empty_btn.clicked.connect(self._on_add_creator)
        empty_btn_layout = QHBoxLayout()
        empty_btn_layout.addStretch(1)
        empty_btn_layout.addWidget(self._empty_btn)
        empty_btn_layout.addStretch(1)
        empty_layout.addLayout(empty_btn_layout)
        empty_layout.addStretch(1)
        self._empty_state.setStyleSheet('background: transparent;')
        self._empty_state.setVisible(False)
        self._stack.addWidget(self._empty_state)
        vbox.addLayout(self._stack, 1)

    def _on_central_resize(self, event) -> None:
        """Keep the gradient canvas covering the entire central widget."""
        self._bg_canvas.resize(self.centralWidget().size())
        QWidget.resizeEvent(self.centralWidget(), event)
    def apply_main_window_qss(self) -> None:
        """Apply MainWindow-specific QSS from the shared stylesheet builder."""
        self.setStyleSheet(build_main_window_qss())

    def _on_theme_changed(self) -> None:
        """React to a theme switch: refresh gradient, stylesheets, and cards."""
        self._bg_canvas.refresh_colors()
        refresh_all_styles()
        # Re-skin cards in place rather than rebuilding them (no DB reload,
        # no cascade animation). Child labels follow the global stylesheet
        # via object-name rules; the card frame is rebuilt per-card.
        for card in self._cards.values():
            if not sip.isdeleted(card):
                card.reapply_theme()
    _CARD_BATCH_SIZE = 20

    def _refresh_cards(self) -> None:
        """Reload creators and cascade-animate cards into view in batches."""
        _, err = load_api_keys(self._db)
        self._banner.setVisible(err is not None)
        if hasattr(self, '_filter_combo'):
            self._refresh_filter_combo()
        scroll_pos = 0
        if hasattr(self, '_scroll'):
            scroll_pos = self._scroll.verticalScrollBar().value()
        for t in self._cascade_timers:
            if not sip.isdeleted(t):
                t.stop()
        self._cascade_timers.clear()
        self._batch_timer.stop()
        for card in self._cards.values():
            self._card_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        self._pending_card_data = []
        last_activity = self._db.bulk_last_activity()
        new_activity_ids = self._db.bulk_new_activity_creators()
        self._sub_counts = self._db.bulk_subscriber_counts()
        sub_counts = self._sub_counts
        creators = self._db.get_creators()
        roles = {r['id']: r for r in self._db.get_roles()}
        roles_list = list(roles.values())
        # Activity sparkline data
        activity = self._db.bulk_activity_sparkline()
        # Subscriber trend arrows (up/down/flat/none) over the snapshot window
        try:
            trends = self._db.bulk_trend_arrows()
        except Exception:
            trends = {}

        # Show/hide empty state
        if not creators:
            self._scroll.setVisible(False)
            self._empty_state.setVisible(True)
            return
        self._scroll.setVisible(True)
        self._empty_state.setVisible(False)

        for c in creators:
            role = roles.get(c.get('role_id'))
            last_act = last_activity.get(c['id'], '')
            has_new_activity = c['id'] in new_activity_ids
            counts = sub_counts.get(c['id'], {})
            sub_text = format_subscriber_count(counts.get('youtube', 0), counts.get('twitch', 0))
            spark = activity.get(c['id'], [])
            trend = trends.get(c['id'], 'none')
            self._pending_card_data.append((c, role, last_act, has_new_activity, sub_text, roles_list, spark, trend))
        # Create first batch immediately
        first_batch = self._pending_card_data[:self._CARD_BATCH_SIZE]
        self._pending_card_data = self._pending_card_data[self._CARD_BATCH_SIZE:]
        first_cards = []
        for c, role, last_act, has_new, sub_text, rlist, spark, trend in first_batch:
            card = CreatorCard(c, role, last_act, has_new, sub_text, roles=rlist, activity_data=spark, trend=trend)
            self._connect_card_signals(card)
            self._cards[c['id']] = card
            self._card_layout.addWidget(card)
            first_cards.append(card)
        self._apply_filter()
        self._apply_sort()
        self._card_container.updateGeometry()
        self._scroll.updateGeometry()
        if hasattr(self, '_scroll') and scroll_pos:
                self._scroll.verticalScrollBar().setValue(scroll_pos)
        self.cascade_cards(first_cards)
        if self._pending_card_data:
            self._batch_timer.start(1)

    def _connect_card_signals(self, card: CreatorCard) -> None:
        """Connect all creator card signals to their handlers."""
        card.edit_requested.connect(self._on_edit_field)
        card.clicked.connect(self._on_card_clicked)
        card.refresh_requested.connect(self._on_refresh_creator)
        card.export_creator_requested.connect(self._on_export_creator)
        card.delete_requested.connect(self._on_delete_creator)
        card.edit_notes_requested.connect(self._on_edit_notes)
        card.role_change_requested.connect(self._on_role_change)
        card.tags_changed.connect(self._on_tags_changed)

    def _on_tags_changed(self, creator_id: int) -> None:
        """Update a single card's tags in-place and re-apply the filter.

        Tag edits don't affect sort order, so this avoids a full grid rebuild
        (and its cascade re-animation) — only the affected card's chips are
        refreshed and the search/role filter is re-evaluated.
        """
        card = self._cards.get(creator_id)
        if card is not None:
            card.refresh_tags()
        self._apply_filter()

    def _create_next_batch(self) -> None:
        """Create the next batch of creator cards (lazy loading)."""
        if not self._pending_card_data:
            return
        batch = self._pending_card_data[:self._CARD_BATCH_SIZE]
        self._pending_card_data = self._pending_card_data[self._CARD_BATCH_SIZE:]
        new_cards = []
        for c, role, last_act, has_new, sub_text, rlist, spark, trend in batch:
            card = CreatorCard(c, role, last_act, has_new, sub_text, roles=rlist, activity_data=spark, trend=trend)
            self._connect_card_signals(card)
            self._cards[c['id']] = card
            self._card_layout.addWidget(card)
            new_cards.append(card)
        self._apply_filter()
        self._apply_sort()
        if new_cards:
            self.cascade_cards(new_cards)
        if self._pending_card_data:
            self._batch_timer.start(1)
    def cascade_cards(self, cards: list[CreatorCard]) -> None:
        """Fade and slide each card up with M.CARD_STAGGER_MS stagger between rows."""
        ANIM_DURATION = 220
        for idx, card in enumerate(cards):
            delay = idx * M.CARD_STAGGER_MS
            effect = QGraphicsOpacityEffect(card)
            effect.setOpacity(0.0)
            card.setGraphicsEffect(effect)
            timer = QTimer(self)
            timer.setSingleShot(True)
            def _launch(c=card, eff=effect, d=ANIM_DURATION, t=timer):
                # This one-shot timer has fired: release it immediately so
                # repeated refreshes don't accumulate stale QTimers on the
                # MainWindow object tree.
                if t in self._cascade_timers:
                    self._cascade_timers.remove(t)
                t.deleteLater()
                if sip.isdeleted(c):
                    return None
                else:
                    op_anim = QPropertyAnimation(eff, b'opacity', c)
                    op_anim.setDuration(d)
                    op_anim.setStartValue(0.0)
                    op_anim.setEndValue(1.0)
                    op_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
                    final_pos = c.pos()
                    start_pos = QPoint(final_pos.x(), final_pos.y() + 20)
                    pos_anim = QPropertyAnimation(c, b'pos', c)
                    pos_anim.setDuration(d)
                    pos_anim.setStartValue(start_pos)
                    pos_anim.setEndValue(final_pos)
                    pos_anim.setEasingCurve(QEasingCurve.Type.OutExpo)
                    op_anim.finished.connect(lambda cc=c: cc.mark_cascade_complete())
                    op_anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
                    pos_anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
            timer.timeout.connect(_launch)
            timer.start(delay)
            self._cascade_timers.append(timer)
    def _refresh_relative_times(self) -> None:
        for card in self._cards.values():
            card.refresh_times()
    def _refresh_filter_combo(self) -> None:
        """Repopulate the role filter dropdown without triggering a filter change.\n\nItems store the role_id as Qt.ItemDataRole.UserRole so the filter can\ncross-reference creator cards by their role_id.\n"""
        self._filter_combo.blockSignals(True)
        self._filter_combo.clear()
        self._filter_combo.addItem('All Roles', None)
        for role in self._db.get_roles():
            self._filter_combo.addItem(role['role_name'], role['id'])
        if self._active_filter_role_id is not None:
            idx = self._filter_combo.findData(self._active_filter_role_id)
            if idx >= 0:
                self._filter_combo.setCurrentIndex(idx)
        self._filter_combo.blockSignals(False)
    def _on_filter_changed(self, index: int) -> None:
        """Update the active filter and apply it when the user selects a role."""
        role_id = self._filter_combo.itemData(index)
        self._active_filter_role_id = role_id
        self._apply_filter()
    def _apply_filter(self) -> None:
        """Show/hide cards based on the selected role filter and search text."""
        for cid, card in self._cards.items():
            role_match = (self._active_filter_role_id is None
                          or card.role_id == self._active_filter_role_id)
            # Search matches nickname or tags
            nickname_match = (not self._search_text
                              or self._search_text in card.creator.get('nickname', '').lower())
            tags_str = ' '.join(
                json.loads(card.creator.get('tags', '[]'))
                if isinstance(card.creator.get('tags', '[]'), str)
                else card.creator.get('tags', [])
            ).lower()
            tag_match = (not self._search_text
                         or self._search_text in tags_str)
            card.setVisible(role_match and (nickname_match or tag_match))
    def _refresh_profile_combo(self) -> None:
        """Repopulate the profile dropdown without triggering a switch."""
        self._profile_combo.blockSignals(True)
        current = self._db.profile
        self._profile_combo.clear()
        for name in self._db.list_profiles():
            self._profile_combo.addItem(name)
        idx = self._profile_combo.findText(current)
        if idx >= 0:
            self._profile_combo.setCurrentIndex(idx)
        self._profile_combo.blockSignals(False)
    def _on_profile_switch(self, index: int) -> None:
        name = self._profile_combo.itemText(index)
        if name == self._db.profile:
            return
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            # Defer the profile switch until the fetch worker finishes
            # to avoid blocking the UI on the DB lock.
            self._fetch_worker.cancel()
            self._pending_profile = name
            self._fetch_status.setVisible(True)
            self._fetch_status.setText(f'Switching to {name}…')
            # Disconnect first to prevent signal accumulation on repeated switches
            try:
                self._fetch_worker.finished.disconnect(self._on_fetch_done_for_profile_switch)
            except (RuntimeError, TypeError):
                pass
            self._fetch_worker.finished.connect(self._on_fetch_done_for_profile_switch)
            return
        self._db.switch_profile(name)
        self._refresh_cards()
        self._refresh_profile_combo()

    def _on_fetch_done_for_profile_switch(self) -> None:
        """Complete a deferred profile switch after the fetch worker finishes."""
        if self._fetch_worker is not None:
            try:
                self._fetch_worker.finished.disconnect(self._on_fetch_done_for_profile_switch)
            except RuntimeError:
                pass
        profile = self._pending_profile
        self._pending_profile = None
        self._fetch_status.setVisible(False)
        if profile and profile != self._db.profile:
            self._db.switch_profile(profile)
            # Re-apply theme for the new profile (each profile may have its own theme)
            saved_theme = self._db.get_setting('theme') or 'default'
            if saved_theme != theme_manager.current:
                theme_manager.apply(saved_theme)
            self._refresh_cards()
            self._refresh_profile_combo()

    def _on_fetch_done_for_import(self) -> None:
        """Complete a deferred profile import after the fetch worker finishes."""
        if self._fetch_worker is not None:
            try:
                self._fetch_worker.finished.disconnect(self._on_fetch_done_for_import)
            except (RuntimeError, TypeError):
                pass
        pending = self._pending_import
        self._pending_import = None
        self._fetch_status.setVisible(False)
        if pending is not None:
            data, profile_name = pending
            try:
                self._db.import_profile(data, profile_name)
                self._db.switch_profile(profile_name)
                self._refresh_cards()
                self._refresh_profile_combo()
                from ui.dialog_utils import dark_info
                dark_info(self, 'Profile Imported', f'Profile "{profile_name}" imported and activated.')
            except Exception as exc:
                from ui.dialog_utils import dark_warning
                dark_warning(self, 'Import Failed', str(exc))
    def _on_add_creator(self) -> None:
        if not self._db.get_roles():
            dark_warning(self, 'No Roles Available', 'You must create at least one role before adding a media member.\nOpen Settings → Roles to create one.')
            return
        dlg = _AddCreatorDialog(self._db, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            vals = dlg.values()
            if vals:
                nick, platforms, role_id, youtube_link, twitch_link = vals
                self._db.add_creator(nick, role_id, platforms, youtube_link=youtube_link, twitch_link=twitch_link)
                self._refresh_cards()
    def _on_edit_field(self, creator_id: int, field: str, current: str) -> None:
        dlg = _InlineEditDialog(field, current, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_val = dlg.value()
            if field == 'nickname':
                self._db.update_creator(creator_id, nickname=new_val)
            elif field == 'platforms':
                self._db.update_creator(creator_id, platforms=json.loads(new_val))
            elif field == 'date_added':
                try:
                    datetime.fromisoformat(new_val.replace('Z', '+00:00'))
                except ValueError:
                    dark_warning(self, 'Invalid Date', 'Enter a valid ISO date (e.g. 2025-01-15T10:30:00Z)')
                    return
                self._db.update_creator(creator_id, date_added=new_val)
            self._refresh_cards()
    def _on_card_clicked(self, creator_id: int) -> None:
        self._db.clear_new_activity(creator_id)
        card = self._cards.get(creator_id)
        if card:
            card.set_new_activity_visible(False)
        creator = self._db.get_creator(creator_id)
        if not creator:
            return
        dlg = HistoryDialog(creator, self._db, self, on_refresh=self.start_fetch)
        dlg.verified_changed.connect(self._refresh_cards)
        dlg.member_deleted.connect(self._refresh_cards)
        self._active_history = dlg
        dlg.exec()
        self._active_history = None
    def _on_refresh_creator(self, creator_id: int) -> None:
        """Re-trigger a data fetch for a specific creator card."""
        self.start_fetch(creator_id=creator_id)

    def _on_refresh_all(self) -> None:
        """Trigger a background fetch for all creators."""
        self.start_fetch()

    def _on_export_creator(self, creator_id: int) -> None:
        """Export a single creator's data to a JSON file."""
        from PyQt6.QtWidgets import QFileDialog
        creator = self._db.get_creator(creator_id)
        if not creator:
            return
        default_name = f"{creator.get('nickname', 'creator')}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export Creator', default_name, 'JSON Files (*.json)')
        if not path:
            return
        try:
            data = self._db.export_creator(creator_id)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            from ui.dialog_utils import dark_info
            dark_info(self, 'Exported', f'Creator exported to {path}')
        except Exception as exc:
            from ui.dialog_utils import dark_warning
            dark_warning(self, 'Export Failed', str(exc))

    def _on_delete_creator(self, creator_id: int) -> None:
        """Delete a creator with confirmation."""
        creator = self._db.get_creator(creator_id)
        if not creator:
            return
        nick = creator.get('nickname', 'Unknown')
        result = dark_question(self, 'Delete Member',
            f'Are you sure you want to permanently delete {nick}?')
        if result == QMessageBox.StandardButton.Yes:
            self._db.delete_creator(creator_id)
            self._refresh_cards()

    def _on_edit_notes(self, creator_id: int) -> None:
        """Open a dialog to edit notes for a creator."""
        creator = self._db.get_creator(creator_id)
        if not creator:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f'Edit Notes — {creator.get("nickname", "Unknown")}')
        dlg.setMinimumWidth(400)
        dlg.setMinimumHeight(250)
        dlg.setStyleSheet(build_dialog_qss())
        layout = QVBoxLayout(dlg)
        notes_edit = QTextEdit()
        notes_edit.setPlainText(creator.get('notes', '') or '')
        layout.addWidget(notes_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._db.update_creator(creator_id, notes=notes_edit.toPlainText())
            self._refresh_cards()

    def _on_search_changed(self, text: str) -> None:
        """Filter visible cards by nickname substring match (debounced)."""
        self._search_text = text.strip().lower()
        self._search_debounce.start()

    def _focus_search(self) -> None:
        """Focus the search bar and select all text (Ctrl+F shortcut)."""
        self._search_edit.setFocus()
        self._search_edit.selectAll()

    def _cycle_theme(self) -> None:
        """Apply the next theme in the registry and persist the choice."""
        names = list(THEME_NAMES)
        try:
            idx = names.index(theme_manager.current)
        except ValueError:
            idx = -1
        nxt = names[(idx + 1) % len(names)]
        theme_manager.apply(nxt)
        self._db.set_setting('theme', nxt)

    def _build_action_registry(self) -> list[Action]:
        """Build the palette action list from existing entry points.

        Per-creator "Open history" jump actions are rebuilt every time the
        palette opens so they reflect the current ``self._cards`` membership.
        """
        actions: list[Action] = [
            Action('add', 'Add Media Member', self._on_add_creator,
                   hint='Ctrl+N', keywords='add new creator member'),
            Action('refresh', 'Refresh All', self._on_refresh_all,
                   hint='Ctrl+R', keywords='refresh fetch update all'),
            Action('verify', 'Verify Media', self._on_verify,
                   hint='', keywords='verify keyword ai gemini claude'),
            Action('settings', 'Settings', self._on_settings,
                   hint='', keywords='settings api keys profiles roles theme'),
            Action('analytics', 'Analytics & Leaderboard', self._on_leaderboard,
                   hint='', keywords='analytics leaderboard charts stats'),
            Action('search', 'Focus Search', self._focus_search,
                   hint='Ctrl+F', keywords='search focus filter find'),
            Action('theme', 'Cycle Theme', self._cycle_theme,
                   hint='', keywords='theme color cycle switch dark light'),
        ]
        for cid, card in self._cards.items():
            nick = card.creator.get('nickname', f'creator {cid}')
            actions.append(Action(
                f'open:{cid}', f'Open History: {nick}',
                lambda c=cid: self._on_card_clicked(c),
                hint='', keywords='open history creator member media',
            ))
        return actions

    def _open_command_palette(self) -> None:
        """Open the Ctrl+K command palette (modal)."""
        palette = CommandPalette(self._build_action_registry(), self)
        palette.exec()

    def _on_role_change(self, creator_id: int, role_id: int) -> None:
        """Handle role change from creator card context menu."""
        self._db.update_creator(creator_id, role_id=role_id)
        self._refresh_cards()

    def _on_sort_changed(self, index: int) -> None:
        """Reorder cards by the selected sort key."""
        self._sort_key = self._sort_combo.currentData() or 'date_added'
        self._apply_sort()

    def _apply_sort(self) -> None:
        """Reorder cards in the layout according to the current sort key."""
        cards = list(self._cards.values())
        if self._sort_key == 'name':
            cards.sort(key=lambda c: c.creator.get('nickname', '').lower())
        elif self._sort_key == 'subscribers':
            sub_counts = getattr(self, '_sub_counts', {})
            def _sub_key(card):
                cid = card.creator_id
                counts = sub_counts.get(cid, {})
                return counts.get('youtube', 0) + counts.get('twitch', 0)
            cards.sort(key=_sub_key, reverse=True)
        else:  # date_added (default, reverse = newest first)
            cards.sort(key=lambda c: c.creator.get('date_added', ''), reverse=True)
        for card in cards:
            self._card_layout.removeWidget(card)
        for card in cards:
            self._card_layout.addWidget(card)

    def _on_settings(self) -> None:
        """Open the full settings dialog (API keys, profiles, roles)."""
        dlg = SettingsDialog(self._db, self, cancel_fetch=self._cancel_fetch)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if dlg.profile_changed:
                self._refresh_profile_combo()
            self._refresh_cards()
    def _on_leaderboard(self) -> None:
        """Open the analytics & leaderboard window."""
        dlg = AnalyticsWindow(self._db, self)
        dlg.exec()
    def _on_verify(self) -> None:
        """Open the Verify dialog and dispatch based on the user's choice."""
        if (self._verify_worker is not None and self._verify_worker.isRunning()) or \
           (self._keyword_worker is not None and self._keyword_worker.isRunning()):
            return
        dlg = VerifyDialog(self._db, self)
        dlg.exec()
        if dlg.result == VerifyResult.KEYWORD:
            self._start_keyword_verify(dlg.keywords)
        elif dlg.result == VerifyResult.AI:
            self._start_ai_verify(dlg.selected_model)

    def _start_ai_verify(self, model: str) -> None:
        """Launch AI verification with the given model."""
        is_gemini = model.startswith('gemini-')
        if is_gemini:
            if not GEMINI_AVAILABLE:
                dark_warning(self, 'Package Missing',
                             "The 'google-genai' Python package is not installed.\n"
                             "Install it with: pip install google-genai")
                return
        else:
            if not ANTHROPIC_AVAILABLE:
                dark_warning(self, 'Package Missing',
                             "The 'anthropic' Python package is not installed.\n"
                             "Install it with: pip install anthropic")
                return
        community_desc = (self._db.get_setting('community_description') or '').strip()
        if not community_desc:
            dark_warning(self, 'No Community Description',
                         'Please enter a community description in Settings → Verify first.')
            return
        raw = self._db.get_global_setting('api_keys_json') or '{}'
        try:
            parsed = json.loads(raw)
            key_field = 'gemini' if is_gemini else 'anthropic'
            api_key = parsed.get(key_field, '').strip() if isinstance(parsed, dict) else ''
        except (json.JSONDecodeError, AttributeError):
            api_key = ''
        if not api_key:
            provider = 'Gemini' if is_gemini else 'Anthropic'
            dark_warning(self, f'No {provider} API Key',
                         f'Please enter your {provider} API key in Settings → API Keys first.')
            return
        if self._verify_worker is not None and self._verify_worker.isRunning():
            return
        unverified = self._db.get_unverified_media()
        total = len(unverified)
        if total == 0:
            dark_info(self, 'All Verified', 'All videos are already verified.')
            return
        self._verify_worker = VerifyWorker(self._db, community_desc, model)
        self._verify_worker.progress.connect(self._on_verify_progress)
        self._verify_worker.progress_text.connect(self._on_verify_progress_text)
        self._verify_worker.video_verified.connect(self._on_video_verified)
        self._verify_worker.done.connect(self._on_verify_done)
        self._verify_worker.error.connect(self._on_verify_error)
        self._verify_worker.api_key_missing.connect(self._on_verify_api_key_missing)
        self._verify_worker.aborted.connect(self._on_verify_aborted)
        self._verify_progress_bar.setValue(0)
        self._verify_progress_label.setText('Preparing…')
        self._verify_progress_area.setVisible(True)
        self._verify_btn.setEnabled(False)
        self._verify_worker.start()

    def _start_keyword_verify(self, keywords_str: str) -> None:
        """Launch keyword verification with the given keywords."""
        keywords = [kw.strip() for kw in keywords_str.split(',') if kw.strip()]
        if not keywords:
            dark_warning(self, 'No Keywords Set',
                         'Please enter at least one keyword, or go back and choose AI verification.')
            return
        if self._keyword_worker is not None and self._keyword_worker.isRunning():
            return
        if self._verify_worker is not None and self._verify_worker.isRunning():
            return
        unverified = self._db.get_unverified_media()
        total = len(unverified)
        if total == 0:
            dark_info(self, 'All Verified', 'All videos are already verified.')
            return
        self._keyword_worker = KeywordVerifyWorker(self._db, keywords)
        self._keyword_worker.progress.connect(self._on_verify_progress)
        self._keyword_worker.progress_text.connect(self._on_keyword_verify_progress_text)
        self._keyword_worker.video_verified.connect(self._on_video_verified)
        self._keyword_worker.done.connect(self._on_keyword_verify_done)
        self._keyword_worker.aborted.connect(self._on_keyword_verify_aborted)
        self._verify_progress_bar.setValue(0)
        self._verify_progress_label.setText('Preparing…')
        self._verify_progress_area.setVisible(True)
        self._verify_btn.setEnabled(False)
        self._keyword_worker.start()
    def _on_verify_progress(self, current: int, total: int) -> None:
        if total > 0:
            self._verify_progress_bar.setValue(int(current / total * 100))
    def _on_verify_progress_text(self, msg: str) -> None:
        self._verify_progress_label.setText(msg)
    def _on_video_verified(self, content_id: str) -> None:
        # Defer full dashboard refresh until verification batch is complete
        # to avoid rebuilding the card grid hundreds of times.
        pass
    def _on_verify_done(self, count: int) -> None:
        self._verify_progress_area.setVisible(False)
        self._verify_btn.setEnabled(True)
        self._cleanup_verify_worker()
        from ui.dialog_utils import dark_info
        dark_info(self, 'Auto-Verify Complete',
                  f'Verified {count} video{"s" if count != 1 else ""}.')
    def _on_verify_error(self, msg: str) -> None:
        self._verify_progress_area.setVisible(False)
        self._verify_btn.setEnabled(True)
        self._cleanup_verify_worker()
        dark_warning(self, 'Auto-Verify Error', msg)
    def _on_verify_api_key_missing(self) -> None:
        self._verify_progress_area.setVisible(False)
        self._verify_btn.setEnabled(True)
        self._cleanup_verify_worker()
        model = self._db.get_setting('auto_verify_model') or 'claude-haiku-4-5-20251001'
        provider = 'Gemini' if model.startswith('gemini-') else 'Anthropic'
        dark_warning(self, f'No {provider} API Key',
                     f'Please enter your {provider} API key in Settings → API Keys.')
    def _on_verify_cancel(self) -> None:
        if self._verify_worker is not None and self._verify_worker.isRunning():
            self._verify_worker.cancel()
            self._verify_cancel_btn.setEnabled(False)
        if self._keyword_worker is not None and self._keyword_worker.isRunning():
            self._keyword_worker.cancel()
            self._verify_cancel_btn.setEnabled(False)
        self._verify_progress_label.setText('Cancelling…')
    def _on_verify_aborted(self) -> None:
        self._verify_progress_area.setVisible(False)
        self._verify_btn.setEnabled(True)
        self._cleanup_verify_worker()
        dark_warning(self, 'Verification Aborted',
                     'Auto-verify was stopped because the active profile was switched.')
    def _cleanup_verify_worker(self) -> None:
        """Disconnect signals and clean up the verify worker reference."""
        if self._verify_worker is not None:
            for signal, slot in [
                (self._verify_worker.progress, self._on_verify_progress),
                (self._verify_worker.progress_text, self._on_verify_progress_text),
                (self._verify_worker.video_verified, self._on_video_verified),
                (self._verify_worker.done, self._on_verify_done),
                (self._verify_worker.error, self._on_verify_error),
                (self._verify_worker.api_key_missing, self._on_verify_api_key_missing),
                (self._verify_worker.aborted, self._on_verify_aborted),
            ]:
                try:
                    signal.disconnect(slot)
                except RuntimeError:
                    pass
            self._verify_worker = None
        self._verify_cancel_btn.setEnabled(True)

    # ── Keyword Verification Handlers ───────────────────────────────────

    def _on_keyword_verify_progress_text(self, msg: str) -> None:
        self._verify_progress_label.setText(msg)

    def _on_keyword_verify_done(self, verified_count: int, total: int) -> None:
        self._verify_progress_area.setVisible(False)
        self._verify_btn.setEnabled(True)
        self._cleanup_keyword_worker()
        dark_info(self, 'Keyword Verify Complete',
                  f'Keyword-matched {verified_count} of {total} video{"s" if total != 1 else ""}.')

    def _on_keyword_verify_aborted(self) -> None:
        self._verify_progress_area.setVisible(False)
        self._verify_btn.setEnabled(True)
        self._cleanup_keyword_worker()
        dark_warning(self, 'Verification Aborted',
                     'Keyword verification was stopped because the active profile was switched.')

    def _cleanup_keyword_worker(self) -> None:
        """Disconnect signals and clean up the keyword verify worker reference."""
        if self._keyword_worker is not None:
            for signal, slot in [
                (self._keyword_worker.progress, self._on_verify_progress),
                (self._keyword_worker.progress_text, self._on_keyword_verify_progress_text),
                (self._keyword_worker.video_verified, self._on_video_verified),
                (self._keyword_worker.done, self._on_keyword_verify_done),
                (self._keyword_worker.aborted, self._on_keyword_verify_aborted),
            ]:
                try:
                    signal.disconnect(slot)
                except RuntimeError:
                    pass
            self._keyword_worker = None
        self._verify_cancel_btn.setEnabled(True)

    def _cleanup_fetch_worker(self) -> None:
        """Disconnect signals and clean up the fetch worker reference."""
        if self._fetch_worker is not None:
            for signal, slot in [
                (self._fetch_worker.finished, self._on_fetch_done),
                (self._fetch_worker.error, self._on_fetch_error),
                (self._fetch_worker.api_key_missing, self._on_api_key_missing),
                (self._fetch_worker.media_fetched, self._on_media_fetched),
                (self._fetch_worker.profile_changed, self._on_profile_changed_during_fetch),
                (self._fetch_worker.cooldown_active, self._on_cooldown),
                (self._fetch_worker.progress, self._on_fetch_progress),
            ]:
                try:
                    signal.disconnect(slot)
                except RuntimeError:
                    pass
            self._fetch_worker = None
    def _restore_refresh_button(self) -> None:
        """Re-enable and restore the text of the Refresh All button."""
        self._refresh_all_btn.setEnabled(True)
        self._refresh_all_btn.setText(self._refresh_all_btn._original_text)

    def _cancel_fetch(self) -> None:
        """Cancel any running fetch worker without blocking the UI."""
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            self._fetch_worker.cancel()
        self._cooldown_timer.stop()
        self._fetch_status.setVisible(False)
        self._cleanup_fetch_worker()

    def start_fetch(self, creator_id: int | None=None) -> None:
        """Kick off a background API fetch.

        When *creator_id* is given, only that creator's data is refreshed.
        Otherwise all creators are fetched.
        """
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            return
        self._fetch_worker = FetchWorker(self._db, creator_id=creator_id)
        self._fetch_worker.finished.connect(self._on_fetch_done)
        self._fetch_worker.error.connect(self._on_fetch_error)
        self._fetch_worker.api_key_missing.connect(self._on_api_key_missing)
        self._fetch_worker.media_fetched.connect(self._on_media_fetched)
        self._fetch_worker.profile_changed.connect(self._on_profile_changed_during_fetch)
        self._fetch_worker.cooldown_active.connect(self._on_cooldown)
        self._fetch_worker.progress.connect(self._on_fetch_progress)
        self._fetch_status.setVisible(True)
        self._fetch_status.setText('Fetching…')
        self._refresh_all_btn.setEnabled(False)
        self._refresh_all_btn.setText('⟳ Refreshing…')
        self._fetch_worker.start()
    def _on_fetch_done(self) -> None:
        """Rebuild cards from DB so fresh PFPs and stats appear immediately.

        Always refreshes cards (partial data may have been fetched even if
        some per-creator errors occurred).  Also refreshes the media history
        dialog if one is open, and check for notification milestones.
        """
        # Clean up any deferred profile switch connection.
        if self._fetch_worker is not None:
            try:
                self._fetch_worker.finished.disconnect(self._on_fetch_done_for_profile_switch)
            except (RuntimeError, TypeError):
                pass
        self._cooldown_timer.stop()
        self._fetch_status.setVisible(False)
        self._restore_refresh_button()
        if self._data_fetched:
            self._refresh_cards()
            # Record a per-creator daily snapshot BEFORE running smart-alert
            # detectors so velocity/inactivity checks see today's numbers.
            try:
                self._db._record_snapshots()
            except Exception as exc:
                logger.warning('Snapshot recording failed: %s', exc)
            self._check_milestones()
        if self._active_history is not None:
            try:
                self._active_history.refresh_completed()
            except RuntimeError:
                pass
        self._data_fetched = False
        self._cleanup_fetch_worker()

    def _check_milestones(self) -> None:
        """Check for subscriber and view milestones after a fetch."""
        sub_counts = self._db.bulk_subscriber_counts()
        creators = self._db.get_creators()
        view_totals = self._db.bulk_view_totals()
        names = {c['id']: c.get('nickname', 'Unknown') for c in creators}
        pending_alerts = []
        for c in creators:
            cid = c['id']
            counts = sub_counts.get(cid, {})
            yt_subs = counts.get('youtube', 0)
            tw_follows = counts.get('twitch', 0)
            max_subs = max(yt_subs, tw_follows)
            if max_subs > 0:
                pending_alerts.extend(self._db.check_subscriber_milestones(cid, max_subs))
            # Check per-creator total views (one bulk query instead of N get_media calls)
            total_views = view_totals.get(cid, 0)
            if total_views > 0:
                pending_alerts.extend(self._db.check_view_thresholds(cid, total_views))
        for alert in pending_alerts:
            name = names.get(alert['creator_id'], 'Unknown')
            if alert['type'] == 'subscriber_milestone':
                threshold = alert['threshold']
                if threshold >= 1_000_000:
                    label = f'{threshold // 1_000_000}M'
                elif threshold >= 1_000:
                    label = f'{threshold // 1_000}K'
                else:
                    label = str(threshold)
                msg = f'{name} reached {label} subscribers!'
            else:
                threshold = alert['threshold']
                if threshold >= 1_000_000:
                    label = f'{threshold // 1_000_000}M'
                elif threshold >= 1_000:
                    label = f'{threshold // 1_000}K'
                else:
                    label = str(threshold)
                msg = f'{name} passed {label} total views!'
            self._show_notification('🎉 Milestone!', msg)

        # ── Smart alerts: velocity spikes + inactivity ──
        try:
            velocity = self._db.check_velocity_alerts()
            for alert in velocity:
                name = names.get(alert['creator_id'], 'Unknown')
                pct = int(alert.get('pct', 0))
                self._show_notification('🚀 Rapid growth!', f'{name} gained {pct}% subscribers recently.')
            inactive = self._db.check_inactivity_alerts()
            for alert in inactive:
                name = names.get(alert['creator_id'], 'Unknown')
                days = alert.get('idle_days', 30)
                self._show_notification('💤 Inactivity', f'{name} has no uploads in {days} days.')
        except Exception as exc:
            logger.warning('Smart-alert check failed: %s', exc)

    def _show_notification(self, title: str, message: str) -> None:
        """Show a toast notification in the top-right corner."""
        toast = NotificationToast(title, message, self)
        toast.show()
    def _on_fetch_error(self, msg: str) -> None:
        """Handle a per-creator fetch error.

        These are non-fatal — the worker continues processing other creators.
        Show the error briefly in the status label, but do NOT restore the
        button or clean up the worker; _on_fetch_done handles that when the
        overall fetch completes.
        """
        logger.warning('Fetch error: %s', msg)
        self._fetch_status.setVisible(True)
        self._fetch_status.setText(f'⚠ {msg}')
    def _on_fetch_progress(self, msg: str) -> None:
        self._fetch_status.setText(msg)
        self._fetch_status.setVisible(True)
    def _on_api_key_missing(self, msg: str) -> None:
        self._banner.setVisible(True)
        self._restore_refresh_button()
        self._cleanup_fetch_worker()
        if self._active_history is not None:
            try:
                self._active_history.refresh_completed()
            except RuntimeError:
                pass
    def _on_media_fetched(self, count: int) -> None:
        self._banner.setVisible(False)
        self._data_fetched = True
    def _on_cooldown(self, remaining: int) -> None:
        """Called when a fetch is skipped because the cooldown is active."""
        logger.info('Fetch skipped — cooldown active, %ds remaining.', remaining)
        self._restore_refresh_button()
        self._cooldown_remaining = remaining
        self._fetch_status.setVisible(True)
        self._fetch_status.setText(f'Cooldown — {remaining}s remaining')
        self._refresh_all_btn.setEnabled(False)
        self._cooldown_timer.start()
        self._cleanup_fetch_worker()
        if self._active_history is not None:
            try:
                self._active_history.refresh_completed()
            except RuntimeError:
                return

    def _cooldown_tick(self) -> None:
        """Count down the cooldown timer and re-enable the Refresh All button when done."""
        self._cooldown_remaining -= 1
        if self._cooldown_remaining <= 0:
            self._cooldown_timer.stop()
            self._fetch_status.setVisible(False)
            self._refresh_all_btn.setEnabled(True)
        else:
            self._fetch_status.setText(f'Cooldown — {self._cooldown_remaining}s remaining')

    def _on_profile_changed_during_fetch(self) -> None:
        """Called when the database profile switches while a fetch is running."""
        self._refresh_cards()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            if self._search_edit.text():
                self._search_edit.clear()
                return
        if handle_fullscreen_keypress(self, event):
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        """Accept dragged .json files for creator or profile import."""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().endswith('.json'):
                    event.acceptProposedAction()
                    return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        """Import a creator or profile from a dropped .json file."""
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.endswith('.json'):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if data.get('type') == 'creator':
                        # Check for duplicate by link before importing
                        c_data = data.get('creator', {})
                        existing_id = self._db.find_creator_by_link(
                            youtube_link=c_data.get('youtube_link'),
                            twitch_link=c_data.get('twitch_link'),
                        )
                        if existing_id is not None:
                            existing = self._db.get_creator(existing_id)
                            existing_name = existing.get('nickname', 'Unknown') if existing else 'Unknown'
                            from ui.dialog_utils import dark_question
                            result = dark_question(
                                self, 'Duplicate Creator',
                                f'A creator named "{existing_name}" already has the same '
                                f'YouTube/Twitch link.\n\nMerge media into the existing creator?',
                            )
                            if result == QMessageBox.StandardButton.Yes:
                                # Merge: add media to existing creator
                                for m in data.get('media_content', []):
                                    self._db.upsert_media(
                                        existing_id, m['platform'], m['content_id'],
                                        title=m.get('title', ''),
                                        thumbnail_path=m.get('thumbnail_path', ''),
                                        thumbnail_url=m.get('thumbnail_url', ''),
                                        upload_date=m.get('upload_date', ''),
                                        view_count=m.get('view_count', 0),
                                        is_short=bool(m.get('is_short', 0)),
                                        description=m.get('description', ''),
                                    )
                                self._refresh_cards()
                                dark_info(self, 'Merged', f'Media merged into "{existing_name}".')
                            else:
                                dark_info(self, 'Skipped', 'Import cancelled.')
                        else:
                            new_id = self._db.import_creator(data)
                            self._refresh_cards()
                            from ui.dialog_utils import dark_info
                            creator = self._db.get_creator(new_id)
                            name = creator.get('nickname', 'Creator') if creator else 'Creator'
                            dark_info(self, 'Imported', f'"{name}" imported successfully.')
                        event.acceptProposedAction()
                        return
                    elif data.get('version') == 1 and 'creators' in data:
                        profile_name = data.get('profile', 'imported')
                        existing = self._db.list_profiles()
                        if profile_name in existing:
                            i = 1
                            while f'{profile_name}_{i}' in existing:
                                i += 1
                            profile_name = f'{profile_name}_{i}'
                        if self._fetch_worker is not None and self._fetch_worker.isRunning():
                            # Defer import until fetch worker finishes to avoid DB lock race
                            self._fetch_worker.cancel()
                            self._pending_import = (data, profile_name)
                            self._fetch_status.setVisible(True)
                            self._fetch_status.setText(f'Importing profile…')
                            try:
                                self._fetch_worker.finished.disconnect(self._on_fetch_done_for_profile_switch)
                            except (RuntimeError, TypeError):
                                pass
                            self._fetch_worker.finished.connect(self._on_fetch_done_for_import)
                        else:
                            self._db.import_profile(data, profile_name)
                            self._db.switch_profile(profile_name)
                            self._refresh_cards()
                            self._refresh_profile_combo()
                            from ui.dialog_utils import dark_info
                            dark_info(self, 'Profile Imported', f'Profile "{profile_name}" imported and activated.')
                        event.acceptProposedAction()
                        return
                    else:
                        from ui.dialog_utils import dark_warning
                        dark_warning(self, 'Invalid File', 'This JSON file is not a recognized Kleos export.')
                        return
                except Exception as exc:
                    from ui.dialog_utils import dark_warning
                    dark_warning(self, 'Import Failed', str(exc))
                    return
        super().dropEvent(event)

    def closeEvent(self, event) -> None:
        running_workers = []
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            running_workers.append(self._fetch_worker)
        if self._verify_worker is not None and self._verify_worker.isRunning():
            running_workers.append(self._verify_worker)

        if not running_workers:
            self._timer.stop()
            if not sip.isdeleted(self._bg_canvas) and hasattr(self._bg_canvas, '_anim'):
                self._bg_canvas._anim.stop()
                try:
                    self._bg_canvas._anim.finished.disconnect(self._bg_canvas._ping_pong)
                except RuntimeError:
                    pass
            save_geometry(self, 'MainWindow', self._db, global_store=True)
            self._db.close()
            super().closeEvent(event)
            return

        if self._pending_close:
            # User clicked close again — force quit.
            # Don't close the DB here; workers may still be using it.
            # Python's shutdown will handle cleanup.
            event.accept()
            return

        # Defer shutdown: cancel workers and wait for them to finish.
        self._pending_close = True
        event.ignore()
        for worker in running_workers:
            # Connect finished BEFORE cancel to avoid a race where the worker
            # finishes between the isRunning() check and the connect() call.
            worker.finished.connect(self._on_worker_finished_for_close)
            if not worker.isRunning():
                # Already finished — handle directly.
                try:
                    worker.finished.disconnect(self._on_worker_finished_for_close)
                except RuntimeError:
                    pass
                self._on_worker_finished_for_close()
            else:
                worker.cancel()
        self._fetch_status.setVisible(True)
        self._fetch_status.setText('Waiting for background tasks…')

    def _on_worker_finished_for_close(self) -> None:
        """Called when a worker finishes during deferred shutdown."""
        still_running = (
            (self._fetch_worker is not None and self._fetch_worker.isRunning())
            or (self._verify_worker is not None and self._verify_worker.isRunning())
        )
        if not still_running:
            self._timer.stop()
            if not sip.isdeleted(self._bg_canvas) and hasattr(self._bg_canvas, '_anim'):
                self._bg_canvas._anim.stop()
                try:
                    self._bg_canvas._anim.finished.disconnect(self._bg_canvas._ping_pong)
                except RuntimeError:
                    pass
            self._db.close()
            self.close()

    def showEvent(self, event) -> None:
        """Resume the refresh timer when the window becomes visible."""
        super().showEvent(event)
        self._timer.start(60000)

    def hideEvent(self, event) -> None:
        """Pause the refresh timer when the window is hidden to save CPU."""
        super().hideEvent(event)
        self._timer.stop()