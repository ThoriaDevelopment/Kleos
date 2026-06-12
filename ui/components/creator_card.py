from __future__ import annotations
import json
import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from ui.theme import C, M
from PyQt6 import sip
from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QSize, Qt, QTimer, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QGridLayout, QLabel, QMenu, QWidget
if TYPE_CHECKING:
    from core.db_manager import DatabaseManager
_ACCENT_R, _ACCENT_G, _ACCENT_B = (QColor(C.ACCENT).red(), QColor(C.ACCENT).green(), QColor(C.ACCENT).blue())
_SHADOW_INIT = QColor(0, 0, 0, 0)
def relative_time(iso_str: str) -> str:
    if not iso_str:
        return 'N/A'
    else:
        try:
            dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return 'N/A'
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = now - dt
        secs = int(diff.total_seconds())
        if secs < 0:
            return 'moments ago'
        else:
            if secs < 60:
                return 'just now'
            else:
                mins = secs // 60
                if mins < 60:
                    return f'{mins} minute{('s' if mins!= 1 else '')} ago'
                else:
                    hours = mins // 60
                    if hours < 24:
                        return f'{hours} hour{('s' if hours!= 1 else '')} ago'
                    else:
                        days = hours // 24
                        if days < 30:
                            return f'{days} day{('s' if days!= 1 else '')} ago'
                        else:
                            months = days // 30
                            if months < 12:
                                return f'{months} month{('s' if months!= 1 else '')} ago'
                            else:
                                years = months // 12
                                return f'{years} year{('s' if years!= 1 else '')} ago'
def membership_duration(iso_str: str) -> str:
    if not iso_str:
        return 'N/A'
    else:
        try:
            dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return 'N/A'
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = now - dt
        days = int(diff.total_seconds()) // 86400
        if days < 1:
            return '< 1 day'
        else:
            if days < 30:
                return f'{days} day{('s' if days!= 1 else '')}'
            else:
                months = days // 30
                if months < 12:
                    return f'{months} month{('s' if months!= 1 else '')}'
                else:
                    years = months // 12
                    rem_months = months % 12
                    if rem_months:
                        return f'{years}y {rem_months}m'
                    else:
                        return f'{years} year{('s' if years!= 1 else '')}'
def _platform_label(platforms: list[str]) -> str:
    has_twitch = 'twitch' in platforms
    has_youtube = 'youtube' in platforms
    if has_twitch and has_youtube:
        return 'Streamer / Creator'
    if has_twitch:
        return 'Streamer'
    else:
        if has_youtube:
            return 'Creator'
        else:
            return 'Unknown'

def _compact_number(n: int) -> str:
    """Format a number in compact form: 1200 → 1.2K, 1500000 → 1.5M."""
    if n >= 1_000_000:
        return f'{n / 1_000_000:.1f}M'
    if n >= 1_000:
        return f'{n / 1_000:.1f}K'
    return str(n)

def format_subscriber_count(yt_subs: int = 0, tw_follows: int = 0) -> str:
    """Format subscriber/follower counts for display on cards and headers.

    Returns a compact string like '1.2M subs  450K flw' or 'N/A' when
    no data is available.
    """
    parts = []
    if yt_subs > 0:
        parts.append(f'{_compact_number(yt_subs)} subs')
    if tw_follows > 0:
        parts.append(f'{_compact_number(tw_follows)} flw')
    return '  '.join(parts) if parts else 'N/A'
def _circular_pixmap(source: QPixmap, size: int) -> QPixmap:
    """Return a copy of *source* clipped to a circle of *size* × *size*.

    The source image is scaled to fill the circle and centred so the
    subject (typically a face) stays in frame regardless of aspect ratio.
    """
    scaled = source.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addEllipse(0, 0, size, size)
        painter.setClipPath(path)
        x_offset = (size - scaled.width()) // 2
        y_offset = (size - scaled.height()) // 2
        painter.drawPixmap(x_offset, y_offset, scaled)
    finally:
        painter.end()
    return out
def _default_avatar_pixmap(size: int) -> QPixmap:
    """Return a circular pixmap with a generic user silhouette fallback."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    bg = QColor(C.AVATAR_BG)
    painter.setBrush(bg)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(0, 0, size, size)
    fg = QColor(C.AVATAR_FG)
    painter.setBrush(fg)
    head_r = int(size * 0.2)
    cx = size // 2
    head_cy = int(size * 0.38)
    painter.drawEllipse(cx - head_r, head_cy - head_r, head_r * 2, head_r * 2)
    body_path = QPainterPath()
    body_w = int(size * 0.65)
    body_h = int(size * 0.3)
    body_x = (size - body_w) // 2
    body_y = int(size * 0.58)
    body_path.addRoundedRect(body_x, body_y, body_w, body_h, body_h // 2, body_h // 2)
    painter.drawPath(body_path)
    painter.end()
    return pm
class _RippleOverlay(QWidget):
    """Full-card overlay that renders a single expanding ripple, then hides."""
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.hide()
        self._radius = 0.0
        self._origin = QPoint(0, 0)
        self._anim = QPropertyAnimation(self, b'ripple_radius', self)
        self._anim.setDuration(340)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._anim.finished.connect(self.hide)
    def _get_radius(self) -> float:
        return self._radius
    def _set_radius(self, val: float) -> None:
        self._radius = val
        self.update()
    ripple_radius = pyqtProperty(float, _get_radius, _set_radius)
    def start(self, origin: QPoint, max_radius: float) -> None:
        self._origin = origin
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(max_radius)
        self.resize(self.parent().size())
        self.raise_()
        self.show()
        self._anim.start()
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        alpha = max(0, int(60 * (1.0 - self._radius / max(self._anim.endValue(), 1))))
        painter.setBrush(QColor(255, 255, 255, alpha))
        painter.setPen(Qt.PenStyle.NoPen)
        r = int(self._radius)
        painter.drawEllipse(self._origin, r, r)
def card_stylesheet(role_color: str | None=None) -> str:
    """Build a per-card stylesheet from design-system tokens."""
    base = 'border-radius: 6px; padding: 4px; background: #222222;'
    child = 'CreatorCard QLabel { background: transparent; color: #E0E0E0; }CreatorCard QWidget { background: transparent; }'
    if not role_color:
        return f'CreatorCard {{ {base} }}' + child
    else:
        c = QColor(role_color)
        if not c.isValid():
            return f'CreatorCard {{ {base} }}' + child
        else:
            border = c.name()
            bg = QColor(c.red(), c.green(), c.blue(), 30).name(QColor.NameFormat.HexArgb)
            return f'CreatorCard {{ {base} border-left: 4px solid {border}; background: {bg}; }}' + child
class CreatorCardAnimMixin:
    """Mixin providing hover animation using design-system motion tokens."""
    def enterEvent(self, event) -> None:
        if self._cascade_animating:
            return super().enterEvent(event)
        if not self._shadow or sip.isdeleted(self._shadow):
            return super().enterEvent(event)
        # Recalculate base position. If the card is currently near its
        # hovered position (base_y - HOVER_LIFT), keep the existing
        # base. Otherwise, the card is at rest so current pos is base.
        if self._base_pos is not None and abs(self.pos().y() - (self._base_pos.y() - M.HOVER_LIFT)) <= 1:
            pass  # Already hovered — keep existing base
        else:
            self._base_pos = self.pos()
        target = QPoint(self._base_pos.x(), self._base_pos.y() - M.HOVER_LIFT)
        self._run_pos_anim(target, M.CARD_HOVER_MS, QEasingCurve.Type.OutQuad)
        self._animate_shadow(blur_target=18, alpha_target=140, duration=M.CARD_HOVER_MS)
        super().enterEvent(event)
    def leaveEvent(self, event) -> None:
        if self._cascade_animating:
            return super().leaveEvent(event)
        if not self._shadow or sip.isdeleted(self._shadow):
            return super().leaveEvent(event)
        if self._base_pos is not None:
            self._run_pos_anim(self._base_pos, M.CARD_HOVER_MS, QEasingCurve.Type.OutQuad)
        self._animate_shadow(blur_target=0, alpha_target=0, duration=M.CARD_HOVER_MS)
        super().leaveEvent(event)
class CreatorCard(CreatorCardAnimMixin, QFrame):
    """A single row/card representing a media member in the dashboard.\n\nAnimation contracts\n-------------------\nhover-enter  → lift M.HOVER_LIFT px (pos), glow shadow fade-in → M.CARD_HOVER_MS\nhover-leave  → restore pos, shadow fade-out                    → M.CARD_HOVER_MS\npress        → scale M.PRESS_SCALE (via geometry shrink trick)  → 50 ms linear\nrelease      → spring back 1.0                                 → 120 ms OutBack\n"""
    edit_requested = pyqtSignal(int, str, str)
    double_clicked = pyqtSignal(int)
    clicked = pyqtSignal(int)
    refresh_requested = pyqtSignal(int)
    export_creator_requested = pyqtSignal(int)
    delete_requested = pyqtSignal(int)
    edit_notes_requested = pyqtSignal(int)
    def __init__(self, creator: dict[str, Any], role: dict[str, Any] | None, last_activity: str, has_new_activity: bool, subscriber_text: str='N/A', parent: QWidget | None=None) -> None:
        super().__init__(parent)
        self._creator = creator
        self._role = role
        self._last_activity_iso = last_activity
        self._has_new_activity = has_new_activity
        self._subscriber_text = subscriber_text
        self._hover_anim = None
        self._shadow_timer = QTimer(self)
        self._shadow_timer.setSingleShot(False)
        self._shadow_timer.setInterval(16)
        self._shadow_tick = None
        self._cascade_animating = True
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(0)
        self._shadow.setOffset(0, 2)
        self._shadow.setColor(_SHADOW_INIT)
        self.setGraphicsEffect(self._shadow)
        self._ripple = _RippleOverlay(self)
        self._base_pos = None
        self._suppress_click = False
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(72)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.setMouseTracking(True)
        role_color = self._role.get('role_color') if self._role else None
        self.setStyleSheet(card_stylesheet(role_color))
        self._build_ui()
    def _build_ui(self) -> None:
        """\nGrid columns (fixed widths keep all rows in perfect alignment):\n\n  col 0  nickname        stretch\n  col 1  avatar          32 px\n  col 2  platform tag   120 px\n  col 3  subscriber      130 px\n  col 4  alert icon      24 px  ← always present, hidden when unused\n  col 5  last activity  140 px\n  col 6  duration        90 px\n"""
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 8, 12, 8)
        grid.setSpacing(8)
        name_font = QFont()
        name_font.setBold(True)
        name_font.setPointSize(11)
        self._name_label = QLabel(self._creator.get('nickname', 'Unknown'))
        self._name_label.setFont(name_font)
        self._name_label.setStyleSheet(f'color: #E0E0E0; background: transparent;')
        grid.addWidget(self._name_label, 0, 0)
        grid.setColumnStretch(0, 1)
        self._avatar_label = QLabel()
        self._avatar_label.setFixedSize(28, 28)
        self._avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar_label.setStyleSheet('background: transparent;')
        self._load_avatar()
        grid.addWidget(self._avatar_label, 0, 1)
        grid.setColumnMinimumWidth(1, 32)
        try:
            platforms = json.loads(self._creator.get('platforms', '[]'))
        except json.JSONDecodeError:
            platforms = []
        tag_text = _platform_label(platforms)
        self._platform_label = QLabel(tag_text)
        self._platform_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._platform_label.setStyleSheet(f'background: rgba(255,255,255,0.08); border-radius: 4px; padding: 2px 10px; font-size: 11px; color: #E0E0E0;')
        grid.addWidget(self._platform_label, 0, 2)
        grid.setColumnMinimumWidth(2, 120)
        self._sub_label = QLabel(self._subscriber_text)
        self._sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_label.setStyleSheet(f'color: {C.TEXT_SECONDARY}; font-size: 11px; background: transparent;')
        grid.addWidget(self._sub_label, 0, 3)
        grid.setColumnMinimumWidth(3, 130)
        self._review_dot = QLabel('⚠')
        self._review_dot.setFixedWidth(24)
        self._review_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._review_dot.setToolTip('New activity — click to inspect')
        self._review_dot.setStyleSheet(f'color: #FF6B35; font-size: 16px; background: transparent;')
        self._review_dot.setVisible(self._has_new_activity)
        grid.addWidget(self._review_dot, 0, 4)
        grid.setColumnMinimumWidth(4, 24)
        self._activity_label = QLabel(relative_time(self._last_activity_iso))
        self._activity_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._activity_label.setStyleSheet(f'color: #E0E0E0; font-size: 11px; background: transparent;')
        grid.addWidget(self._activity_label, 0, 5)
        grid.setColumnMinimumWidth(5, 140)
        date_added = self._creator.get('date_added', '')
        self._duration_label = QLabel(membership_duration(date_added))
        self._duration_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._duration_label.setStyleSheet(f'color: #E0E0E0; font-size: 11px; background: transparent;')
        grid.addWidget(self._duration_label, 0, 6)
        grid.setColumnMinimumWidth(6, 90)
    def _load_avatar(self) -> None:
        pfp = self._creator.get('pfp_url')
        if pfp:
            px = QPixmap(pfp)
            if not px.isNull():
                self._avatar_label.setPixmap(_circular_pixmap(px, 28))
                return
        self._avatar_label.setPixmap(_default_avatar_pixmap(28))
    def refresh_pfp(self) -> None:
        """Reload avatar from the current creator record and redraw."""
        self._load_avatar()
        self.update()
    def _animate_shadow(self, blur_target: int, alpha_target: int, duration: int=M.CARD_HOVER_MS) -> None:
        """Smoothly drive the drop-shadow blur/alpha via the card\'s persistent timer."""
        if not self._shadow or sip.isdeleted(self._shadow):
            return None
        else:
            self._shadow_timer.stop()
            if self._shadow_tick is not None:
                try:
                    self._shadow_timer.timeout.disconnect(self._shadow_tick)
                except (RuntimeError, TypeError):
                    pass
                self._shadow_tick = None
            steps = max(1, duration // 16)
            start_blur = self._shadow.blurRadius()
            start_alpha = self._shadow.color().alpha()
            step_ref = [0]
            def _tick():
                if not self._shadow or sip.isdeleted(self._shadow):
                    self._shadow_timer.stop()
                    return None
                else:
                    t = min(1.0, (step_ref[0] + 1) / steps)
                    new_blur = start_blur + (blur_target - start_blur) * t
                    new_alpha = int(start_alpha + (alpha_target - start_alpha) * t)
                    self._shadow.setBlurRadius(new_blur)
                    self._shadow.setColor(QColor(_ACCENT_R, _ACCENT_G, _ACCENT_B, new_alpha))
                    step_ref[0] += 1
                    if step_ref[0] >= steps:
                        self._shadow_timer.stop()
                        self._shadow_timer.timeout.disconnect(self._shadow_tick)
                        self._shadow_tick = None
            self._shadow_tick = _tick
            self._shadow_timer.timeout.connect(self._shadow_tick)
            self._shadow_timer.start(16)
    def mark_cascade_complete(self) -> None:
        """Signal that the startup entry animation has finished.\n\nCalled by the dashboard after the fade-in cascade completes.\nRe-installs the drop-shadow effect (which the cascade replaces\nwith a QGraphicsOpacityEffect) and flips the flag so hover\ninteractions are no longer suppressed.\n"""
        self._cascade_animating = False
        if not self._shadow or sip.isdeleted(self._shadow):
            self._shadow = QGraphicsDropShadowEffect(self)
            self._shadow.setBlurRadius(0)
            self._shadow.setOffset(0, 2)
            self._shadow.setColor(_SHADOW_INIT)
        self.setGraphicsEffect(self._shadow)
        self._base_pos = self.pos()
    def _run_pos_anim(self, target: QPoint, duration: int, curve: QEasingCurve.Type) -> None:
        if self._hover_anim:
            if sip.isdeleted(self._hover_anim):
                self._hover_anim = None
            else:
                self._hover_anim.stop()
                self._hover_anim.deleteLater()
                self._hover_anim = None
        anim = QPropertyAnimation(self, b'pos', self)
        anim.setDuration(duration)
        anim.setEndValue(target)
        anim.setEasingCurve(curve)
        anim.finished.connect(anim.deleteLater)
        anim.start()
        self._hover_anim = anim
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
        else:
            if sip.isdeleted(self):
                event.accept()
                return None
            else:
                corner_dist = math.hypot(self.width(), self.height())
                self._ripple.start(event.pos(), corner_dist * 0.8)
                # Brief opacity dip for press feedback (avoids layout flicker from geometry animation)
                press_effect = QGraphicsOpacityEffect(self)
                press_effect.setOpacity(0.7)
                self.setGraphicsEffect(press_effect)
                release_anim = QPropertyAnimation(press_effect, b'opacity', self)
                release_anim.setDuration(120)
                release_anim.setStartValue(0.7)
                release_anim.setEndValue(1.0)
                release_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
                release_anim.finished.connect(self._restore_effect)
                release_anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
                try:
                    super().mousePressEvent(event)
                except RuntimeError:
                    event.accept()

    def _restore_effect(self) -> None:
        """Restore the shadow effect after the press animation finishes."""
        if sip.isdeleted(self):
            return
        if not self._shadow or sip.isdeleted(self._shadow):
            self._shadow = QGraphicsDropShadowEffect(self)
            self._shadow.setBlurRadius(0)
            self._shadow.setOffset(0, 2)
            self._shadow.setColor(_SHADOW_INIT)
        self.setGraphicsEffect(self._shadow)
    def refresh_times(self) -> None:
        self._activity_label.setText(relative_time(self._last_activity_iso))
        date_added = self._creator.get('date_added', '')
        self._duration_label.setText(membership_duration(date_added))
    def set_new_activity_visible(self, visible: bool) -> None:
        self._has_new_activity = visible
        self._review_dot.setVisible(visible)
    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.setStyleSheet('QMenu { background-color: #1C1C22; border: 1px solid #3A3A3A; }QMenu::item { color: #E0E0E0; padding: 6px 20px; }QMenu::item:selected { background-color: #2A2A33; color: #FFFFFF; }')
        edit_nick = QAction('Edit Nickname', self)
        edit_nick.triggered.connect(lambda: self.edit_requested.emit(self._creator['id'], 'nickname', self._creator.get('nickname', '')))
        menu.addAction(edit_nick)
        edit_plat = QAction('Edit Platforms', self)
        edit_plat.triggered.connect(lambda: self.edit_requested.emit(self._creator['id'], 'platforms', self._creator.get('platforms', '[]')))
        menu.addAction(edit_plat)
        edit_date = QAction('Edit Date Added', self)
        edit_date.triggered.connect(lambda: self.edit_requested.emit(self._creator['id'], 'date_added', self._creator.get('date_added', '')))
        menu.addAction(edit_date)
        menu.addSeparator()
        refresh_action = QAction('Refresh Data', self)
        refresh_action.triggered.connect(lambda: self.refresh_requested.emit(self._creator['id']))
        menu.addAction(refresh_action)
        menu.addSeparator()
        delete_action = QAction('Delete Member', self)
        delete_action.triggered.connect(lambda: self.delete_requested.emit(self._creator['id']))
        menu.addAction(delete_action)
        edit_notes_action = QAction('Edit Notes', self)
        edit_notes_action.triggered.connect(lambda: self.edit_notes_requested.emit(self._creator['id']))
        menu.addAction(edit_notes_action)
        menu.addSeparator()
        export_action = QAction('Export Creator', self)
        export_action.triggered.connect(lambda: self.export_creator_requested.emit(self._creator['id']))
        menu.addAction(export_action)
        menu.exec(self.mapToGlobal(pos))
    def mouseDoubleClickEvent(self, event) -> None:
        if event.button()!= Qt.MouseButton.LeftButton:
            event.accept()
            return None
        else:
            if sip.isdeleted(self):
                event.accept()
            else:
                self._suppress_click = True
                self.double_clicked.emit(self._creator['id'])
                try:
                    super().mouseDoubleClickEvent(event)
                except RuntimeError:
                    event.accept()
    def mouseReleaseEvent(self, event) -> None:
        if event.button()!= Qt.MouseButton.LeftButton:
            event.accept()
            return None
        else:
            if sip.isdeleted(self):
                event.accept()
            else:
                if self._suppress_click:
                    self._suppress_click = False
                    event.accept()
                    return None
                self.clicked.emit(self._creator['id'])
                try:
                    super().mouseReleaseEvent(event)
                except RuntimeError:
                    event.accept()
    @property
    def creator_id(self) -> int:
        return self._creator['id']
    @property
    def creator(self) -> dict[str, Any]:
        return self._creator
    @property
    def platforms(self) -> list[str]:
        try:
            return json.loads(self._creator.get('platforms', '[]'))
        except json.JSONDecodeError:
            return []
    @property
    def role_id(self) -> int | None:
        return self._creator.get('role_id')