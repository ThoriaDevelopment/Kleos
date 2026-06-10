from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Any
from ui.theme import C, M
from PyQt6 import sip
from PyQt6.QtCore import QAbstractAnimation, QDate, QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPalette
from PyQt6.QtWidgets import QCalendarWidget, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QProgressBar, QScrollArea, QStackedWidget, QVBoxLayout, QWidget
from core.api_client import FetchWorker, load_api_keys
from core.db_manager import DatabaseManager
from core.verify_worker import ANTHROPIC_AVAILABLE, VerifyWorker
logger = logging.getLogger(__name__)
from ui.app_icon import create_app_icon
from ui.components.creator_card import CreatorCard, format_subscriber_count
from ui.components.history_dialog import HistoryDialog
from ui.dialog_utils import dark_warning, handle_fullscreen_keypress
from ui.settings_dialog import SettingsDialog
from ui.analytics_window import AnalyticsWindow
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
class _InlineEditDialog(QDialog):
    _CALENDAR_QSS = 'QCalendarWidget { background: #222222; color: #E0E0E0; }QCalendarWidget QToolButton { color: #E0E0E0; background: #222222; border: 1px solid #3A3A3A; }QCalendarWidget QMenu { background: #3A3A3A; color: #E0E0E0; }QCalendarWidget QAbstractItemView { background: #222222; selection-background-color: #E0E0E0; border: none; padding: 4px; }#qt_calendar_yearbutton:hover { background: #222222; color: #E0E0E0; }#qt_calendar_yearedit { color: #E0E0E0; }#qt_calendar_prevmonth { background: #222222; border: none; }#qt_calendar_nextmonth { background: #222222; border: none; }QCalendarWidget QTableView { background: #3A3A3A; gridline-color: #4A90D9; selection-color: #FFFFFF; alternate-background-color: #0F0F14; }'
    def __init__(self, field: str, current_value: str, parent: QWidget | None=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f'Edit {field.replace('_', ' ').title()}')
        self.setMinimumWidth(320)
        self.setStyleSheet('QDialog { background: #09090C; }QLabel { color: #E0E0E0; background: transparent; }QLineEdit { background: #222222; color: #E0E0E0; border: 1px solid #3A3A3A; border-radius: 4px; padding: 4px 8px; }QListWidget { background: #222222; color: #E0E0E0; border: 1px solid #3A3A3A; border-radius: 4px; }QListWidget::item:selected { background: #2A2A33; }QCheckBox { color: #E0E0E0; border: 1px solid #3A5A8C; }QPushButton { background: #1C1C22; color: #E0E0E0; border: 1px solid #3A3A3A; border-radius: 4px; padding: 6px 14px; }QPushButton:hover { background: #2A2A33; }QDialogButtonBox { background: transparent; }')
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
        label.setStyleSheet(f'font-size: 14px; color: #FF6B35; background: transparent;')
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
        self.setStyleSheet('QDialog { background: #09090C; }QLabel { color: #E0E0E0; background: transparent; }QLineEdit { background: #222222; color: #E0E0E0; border: 1px solid #3A3A3A; border-radius: 4px; padding: 4px 8px; }QLineEdit::placeholder { color: rgba(224,224,224,0.4); }QComboBox { background: #222222; color: #E0E0E0; border: 1px solid #3A3A3A; border-radius: 4px; padding: 4px 8px; }QComboBox QAbstractItemView { background: #1C1C22; color: #E0E0E0; border: 1px solid #3A3A3A; selection-background-color: #2A2A33; }QListWidget { background: #222222; color: #E0E0E0; border: 1px solid #3A5A8C; }QPushButton { background: #1C1C22; color: #E0E0E0; border: 1px solid #3A3A3A; border-radius: 4px; padding: 6px 14px; }QPushButton:hover { background: #2A2A33; }QDialogButtonBox { background: transparent; }')
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
        plat_container.setStyleSheet('QWidget { background: #222222; border: 1px solid #3A3A3A; border-radius: 4px; }QCheckBox { outline: none; }QCheckBox::focus { outline: none; }')
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
        self._fetch_worker = None
        self._verify_worker = None
        self._active_history = None
        self._active_filter_role_id = None
        self._data_fetched = False
        self._search_text = ''
        self._sort_key = 'date_added'
        self._cascade_timers = []
        self.setWindowTitle('Kleos — Media Dashboard')
        self.setWindowIcon(create_app_icon())
        self.setMinimumSize(800, 520)
        self.resize(960, 640)
        self.setAcceptDrops(True)
        self._build_ui()
        self.apply_main_window_qss()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_relative_times)
        self._timer.start(60000)
        self._refresh_cards()
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
        add_btn.clicked.connect(self._on_add_creator)
        top_row1.addWidget(add_btn)
        top_row1.addSpacing(8)
        self._refresh_all_btn = QPushButton('⟳ Refresh All')
        self._refresh_all_btn.clicked.connect(self._on_refresh_all)
        top_row1.addWidget(self._refresh_all_btn)
        top_row1.addStretch(1)
        self._verify_btn = QPushButton('✓ Auto-Verify')
        self._verify_btn.clicked.connect(self._on_auto_verify)
        top_row1.addWidget(self._verify_btn)
        top_row1.addSpacing(8)
        settings_btn = QPushButton('⚙ Settings')
        settings_btn.clicked.connect(self._on_settings)
        top_row1.addWidget(settings_btn)
        top_row1.addSpacing(8)
        leaderboard_btn = QPushButton('♛ Leaderboard')
        leaderboard_btn.clicked.connect(self._on_leaderboard)
        top_row1.addWidget(leaderboard_btn)
        top_row2 = QHBoxLayout()
        top_row2.setContentsMargins(16, 2, 16, 8)
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText('Search members…')
        self._search_edit.setFixedWidth(180)
        self._search_edit.textChanged.connect(self._on_search_changed)
        top_row2.addWidget(self._search_edit)
        top_row2.addSpacing(8)
        self._fetch_status = QLabel('')
        self._fetch_status.setStyleSheet(f'color: {C.TEXT_SECONDARY}; font-size: 11px; background: transparent;')
        self._fetch_status.setVisible(False)
        top_row2.addWidget(self._fetch_status)
        top_row2.addStretch(1)
        top_row2.addWidget(QLabel('Sort: '))
        self._sort_combo = QComboBox()
        self._sort_combo.addItem('Date Added', 'date_added')
        self._sort_combo.addItem('Name', 'name')
        self._sort_combo.addItem('Subscribers', 'subscribers')
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        top_row2.addWidget(self._sort_combo)
        top_row2.addSpacing(8)
        top_row2.addWidget(QLabel('Filter: '))
        self._filter_combo = QComboBox()
        self._refresh_filter_combo()
        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        top_row2.addWidget(self._filter_combo)
        top_row2.addSpacing(8)
        top_row2.addWidget(QLabel('Profile: '))
        self._profile_combo = QComboBox()
        self._refresh_profile_combo()
        self._profile_combo.currentIndexChanged.connect(self._on_profile_switch)
        top_row2.addWidget(self._profile_combo)
        top_vbox = QVBoxLayout()
        top_vbox.setContentsMargins(0, 0, 0, 0)
        top_vbox.setSpacing(0)
        top_vbox.addLayout(top_row1)
        top_vbox.addLayout(top_row2)
        top_container = QWidget()
        top_container.setStyleSheet('background: rgba(0,0,0,0.35);')
        top_container.setLayout(top_vbox)
        vbox.addWidget(top_container)
        # Progress bar area for auto-verify (hidden by default)
        self._verify_progress_area = QWidget()
        self._verify_progress_area.setVisible(False)
        progress_layout = QHBoxLayout(self._verify_progress_area)
        progress_layout.setContentsMargins(16, 6, 16, 6)
        self._verify_progress_label = QLabel('')
        self._verify_progress_label.setStyleSheet(f'color: {C.TEXT_SECONDARY}; background: transparent;')
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
        sep.setStyleSheet(f'background: #3A3A3A;')
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
        vbox.addLayout(self._stack, 1)
    def _on_central_resize(self, event) -> None:
        """Keep the gradient canvas covering the entire central widget."""
        self._bg_canvas.resize(self.centralWidget().size())
        QWidget.resizeEvent(self.centralWidget(), event)
    def apply_main_window_qss(self) -> None:
        """Apply MainWindow-specific QSS overrides using design-system tokens.\n\nSupplements the global stylesheet (build_global_qss) applied in\nmain.py.  Only MainWindow-specific selectors are set here; common\nwidget styles are inherited from the application stylesheet.\n"""
        self.setStyleSheet(
            f'QMainWindow {{ background: #0F0F14; }}\n'
            f'QCheckBox::indicator:checked {{ image: none; }}\n'
        )
    def _refresh_cards(self) -> None:
        """Reload creators and cascade-animate cards into view."""
        _, err = load_api_keys(self._db)
        self._banner.setVisible(err is not None)
        if hasattr(self, '_filter_combo'):
            self._refresh_filter_combo()
        scroll_pos = 0
        if hasattr(self, '_scroll'):
            scroll_pos = self._scroll.verticalScrollBar().value()
        for t in self._cascade_timers:
            t.stop()
        self._cascade_timers.clear()
        for card in self._cards.values():
            self._card_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        last_activity = self._db.bulk_last_activity()
        new_activity_ids = self._db.bulk_new_activity_creators()
        self._sub_counts = self._db.bulk_subscriber_counts()
        sub_counts = self._sub_counts
        creators = self._db.get_creators()
        roles = {r['id']: r for r in self._db.get_roles()}
        new_cards = []
        for c in creators:
            role = roles.get(c.get('role_id'))
            last_act = last_activity.get(c['id'], '')
            has_new_activity = c['id'] in new_activity_ids
            counts = sub_counts.get(c['id'], {})
            sub_text = format_subscriber_count(counts.get('youtube', 0), counts.get('twitch', 0))
            card = CreatorCard(c, role, last_act, has_new_activity, sub_text)
            card.edit_requested.connect(self._on_edit_field)
            card.clicked.connect(self._on_card_clicked)
            card.refresh_requested.connect(self._on_refresh_creator)
            card.export_creator_requested.connect(self._on_export_creator)
            self._cards[c['id']] = card
            self._card_layout.addWidget(card)
            new_cards.append(card)
        self._apply_filter()
        self._apply_sort()
        self._card_container.updateGeometry()
        self._scroll.updateGeometry()
        if hasattr(self, '_scroll') and scroll_pos:
                self._scroll.verticalScrollBar().setValue(scroll_pos)
        self.cascade_cards(new_cards)
    def cascade_cards(self, cards: list[CreatorCard]) -> None:
        """Fade and slide each card up with M.CARD_STAGGER_MS stagger between rows."""
        ANIM_DURATION = 220
        for idx, card in enumerate(cards):
            delay = idx * M.CARD_STAGGER_MS
            effect = QGraphicsOpacityEffect(card)
            effect.setOpacity(0.0)
            card.setGraphicsEffect(effect)
            def _launch(c=card, eff=effect, d=ANIM_DURATION):
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
            timer = QTimer(self)
            timer.setSingleShot(True)
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
            search_match = (not self._search_text
                            or self._search_text in card.creator.get('nickname', '').lower())
            card.setVisible(role_match and search_match)
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
            self._fetch_worker.cancel()
        self._db.switch_profile(name)
        self._refresh_cards()
        self._refresh_profile_combo()
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
        import json as _json
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
                _json.dump(data, f, indent=2, ensure_ascii=False)
            from ui.dialog_utils import dark_info
            dark_info(self, 'Exported', f'Creator exported to {path}')
        except Exception as exc:
            from ui.dialog_utils import dark_warning
            dark_warning(self, 'Export Failed', str(exc))

    def _on_search_changed(self, text: str) -> None:
        """Filter visible cards by nickname substring match."""
        self._search_text = text.strip().lower()
        self._apply_filter()

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
    def _on_auto_verify(self) -> None:
        """Kick off auto-verification of unverified media via the Claude API."""
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
        import json
        raw = self._db.get_setting('api_keys_json') or '{}'
        try:
            parsed = json.loads(raw)
            api_key = parsed.get('anthropic', '').strip() if isinstance(parsed, dict) else ''
        except (json.JSONDecodeError, AttributeError):
            api_key = ''
        if not api_key:
            dark_warning(self, 'No Anthropic API Key',
                         'Please enter your Anthropic API key in Settings → API Keys first.')
            return
        if self._verify_worker is not None and self._verify_worker.isRunning():
            return
        model = self._db.get_setting('auto_verify_model') or 'claude-haiku-4-5'
        model_labels = {'claude-haiku-4-5': 'Haiku 4.5', 'claude-sonnet-4-6': 'Sonnet 4.6', 'claude-opus-4-8': 'Opus 4.8'}
        unverified = self._db.get_unverified_media()
        total = len(unverified)
        if total == 0:
            from ui.dialog_utils import dark_info
            dark_info(self, 'All Verified', 'All videos are already verified.')
            return
        from ui.dialog_utils import dark_question
        model_label = model_labels.get(model, model)
        confirm = dark_question(
            self, 'Auto-Verify',
            f'This will verify {total} unverified video{"s" if total != 1 else ""} '
            f'using {model_label}.\n\nContinue?'
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._verify_worker = VerifyWorker(self._db, community_desc, model)
        self._verify_worker.progress.connect(self._on_verify_progress)
        self._verify_worker.progress_text.connect(self._on_verify_progress_text)
        self._verify_worker.video_verified.connect(self._on_video_verified)
        self._verify_worker.done.connect(self._on_verify_done)
        self._verify_worker.error.connect(self._on_verify_error)
        self._verify_worker.api_key_missing.connect(self._on_verify_api_key_missing)
        self._verify_progress_bar.setValue(0)
        self._verify_progress_label.setText('Preparing…')
        self._verify_progress_area.setVisible(True)
        self._verify_btn.setEnabled(False)
        self._verify_worker.start()
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
        dark_warning(self, 'No Anthropic API Key',
                     'Please enter your Anthropic API key in Settings → API Keys.')
    def _on_verify_cancel(self) -> None:
        if self._verify_worker is not None and self._verify_worker.isRunning():
            self._verify_worker.cancel()
        self._verify_progress_label.setText('Cancelling…')
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
            ]:
                try:
                    signal.disconnect(slot)
                except RuntimeError:
                    pass
            self._verify_worker = None
    def _cancel_fetch(self) -> None:
        """Cancel any running fetch worker without blocking the UI."""
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            self._fetch_worker.cancel()
            self._fetch_status.setVisible(False)

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
        self._fetch_worker.start()
    def _on_fetch_done(self) -> None:
        """Rebuild cards from DB so fresh PFPs and stats appear immediately.

        Only refreshes if data was actually fetched (media_fetched was emitted).
        Also refreshes the media history dialog if one is open.
        """
        self._fetch_status.setVisible(False)
        self._refresh_all_btn.setEnabled(True)
        if self._data_fetched:
            self._refresh_cards()
            if self._active_history is not None:
                try:
                    self._active_history.refresh_completed()
                except RuntimeError:
                    pass
        self._data_fetched = False
    def _on_fetch_error(self, msg: str) -> None:
        logger.warning('Fetch error: %s', msg)
        self._fetch_status.setVisible(False)
        self._refresh_all_btn.setEnabled(True)
        if self._active_history is not None:
            try:
                self._active_history.refresh_completed()
            except RuntimeError:
                pass
    def _on_fetch_progress(self, msg: str) -> None:
        self._fetch_status.setText(msg)
        self._fetch_status.setVisible(True)
    def _on_api_key_missing(self, msg: str) -> None:
        self._banner.setVisible(True)
        self._refresh_all_btn.setEnabled(True)
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
        self._refresh_all_btn.setEnabled(True)
        self._fetch_status.setVisible(False)
        if self._active_history is not None:
            try:
                self._active_history.refresh_completed()
            except RuntimeError:
                return

    def _on_profile_changed_during_fetch(self) -> None:
        """Called when the database profile switches while a fetch is running."""
        self._refresh_cards()

    def keyPressEvent(self, event) -> None:  # noqa: N802
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
                    import json as _json
                    with open(path, 'r', encoding='utf-8') as f:
                        data = _json.load(f)
                    if data.get('type') == 'creator':
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
                            self._fetch_worker.cancel()
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
        self._timer.stop()
        self._bg_canvas._anim.stop()
        try:
            self._bg_canvas._anim.finished.disconnect(self._bg_canvas._ping_pong)
        except RuntimeError:
            pass
        if self._fetch_worker is not None:
            self._fetch_worker.cancel()
            self._fetch_worker.wait(5000)
            self._fetch_worker.finished.connect(self._fetch_worker.deleteLater)
            for signal, slot in [(self._fetch_worker.finished, self._on_fetch_done), (self._fetch_worker.error, self._on_fetch_error), (self._fetch_worker.api_key_missing, self._on_api_key_missing), (self._fetch_worker.media_fetched, self._on_media_fetched), (self._fetch_worker.profile_changed, self._on_profile_changed_during_fetch), (self._fetch_worker.cooldown_active, self._on_cooldown), (self._fetch_worker.progress, self._on_fetch_progress)]:
                try:
                    signal.disconnect(slot)
                except RuntimeError:
                    pass
            self._fetch_worker = None
        if self._verify_worker is not None:
            self._verify_worker.cancel()
            self._verify_worker.wait(5000)
            self._verify_worker.finished.connect(self._verify_worker.deleteLater)
            for signal, slot in [(self._verify_worker.progress, self._on_verify_progress), (self._verify_worker.progress_text, self._on_verify_progress_text), (self._verify_worker.video_verified, self._on_video_verified), (self._verify_worker.done, self._on_verify_done), (self._verify_worker.error, self._on_verify_error), (self._verify_worker.api_key_missing, self._on_verify_api_key_missing)]:
                try:
                    signal.disconnect(slot)
                except RuntimeError:
                    pass
            self._verify_worker = None
        self._db.close()
        super().closeEvent(event)