from __future__ import annotations
import json
import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from ui.theme import C, M
from PyQt6 import sip
from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QSize, Qt, QTimer, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QMenu, QWidget
if TYPE_CHECKING:
    from core.db_manager import DatabaseManager
_SHADOW_INIT = QColor(0, 0, 0, 0)


class _SparklineWidget(QWidget):
    """Tiny row of dots showing upload frequency over the last N weeks."""

    def __init__(self, data: list[int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data = data or [0] * 7
        self.setFixedSize(max(len(self._data) * 8 + 4, 10), 14)
        self.setStyleSheet('background: transparent;')

    def update_data(self, data: list[int]) -> None:
        self._data = data or [0] * 7
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        max_val = max(self._data) if self._data else 1
        max_val = max(max_val, 1)
        for i, val in enumerate(self._data):
            alpha = max(40, min(220, int(40 + 180 * (val / max_val))))
            radius = max(2, min(4, int(2 + 2 * (val / max_val))))
            dot = QColor(C.ACCENT)
            dot.setAlpha(alpha)
            painter.setBrush(dot)
            painter.setPen(Qt.PenStyle.NoPen)
            center_x = 4 + i * 8
            center_y = 7
            painter.drawEllipse(QPoint(center_x, center_y), radius, radius)
        painter.end()


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
        # Use accent colour for ripple so it's visible on both light and dark themes
        ripple_color = QColor(C.ACCENT)
        ripple_color.setAlpha(alpha)
        painter.setBrush(ripple_color)
        painter.setPen(Qt.PenStyle.NoPen)
        r = int(self._radius)
        painter.drawEllipse(self._origin, r, r)
def card_stylesheet(role_color: str | None=None, focused: bool=False) -> str:
    """Build the per-card frame stylesheet from design-system tokens.

    This is the dynamic-style escape hatch: the role colour is an arbitrary
    runtime hex string that cannot be expressed as a static QSS selector, so
    the card frame (border, background tint, focus ring) is rebuilt here and
    re-applied by :meth:`CreatorCard.reapply_theme` on theme switches. Child
    labels are styled by object-name rules in ``build_global_qss`` and so
    follow theme changes automatically without this call.
    """
    base = f'border-radius: 6px; padding: 4px; background: {C.CARD_BG};'
    if focused:
        base += f' border: 2px solid {C.ACCENT};'
    child = 'CreatorCard QWidget { background: transparent; }'
    if not role_color:
        return f'CreatorCard {{ {base} }}' + child
    c = QColor(role_color)
    if not c.isValid():
        return f'CreatorCard {{ {base} }}' + child
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
    role_change_requested = pyqtSignal(int, int)
    tags_changed = pyqtSignal(int)

    def __init__(self, creator: dict[str, Any], role: dict[str, Any] | None, last_activity: str, has_new_activity: bool, subscriber_text: str='N/A', roles: list[dict[str, Any]] | None=None, activity_data: list[int] | None=None, trend: str='none', parent: QWidget | None=None) -> None:
        super().__init__(parent)
        self._creator = creator
        self._role = role
        self._last_activity_iso = last_activity
        self._has_new_activity = has_new_activity
        self._subscriber_text = subscriber_text
        self._roles = roles or []
        self._activity_data = activity_data or []
        self._trend = trend if trend in ('up', 'down', 'flat', 'none') else 'none'
        self._hover_anim = None
        self._focused = False
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
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(72)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.setMouseTracking(True)
        role_color = self._role.get('role_color') if self._role else None
        self.setStyleSheet(card_stylesheet(role_color))
        self._build_ui()
        self._refresh_trend_label()
    def _build_ui(self) -> None:
        """\nGrid columns (fixed widths keep all rows in perfect alignment):\n\n  col 0  nickname        stretch\n  col 1  avatar          32 px\n  col 2  platform tag   120 px\n  col 3  subscriber      130 px\n  col 4  alert icon      24 px  ← always present, hidden when unused\n  col 5  sparkline       64 px  ← activity dots\n  col 6  last activity  140 px\n  col 7  duration        90 px\n"""
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 8, 12, 8)
        grid.setSpacing(8)
        name_font = QFont()
        name_font.setBold(True)
        name_font.setPointSize(11)
        self._name_label = QLabel(self._creator.get('nickname', 'Unknown'))
        self._name_label.setFont(name_font)
        self._name_label.setObjectName('cardName')
        grid.addWidget(self._name_label, 0, 0)
        grid.setColumnStretch(0, 1)
        self._avatar_label = QLabel()
        self._avatar_label.setFixedSize(28, 28)
        self._avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        self._platform_label.setObjectName('cardPlatformTag')
        grid.addWidget(self._platform_label, 0, 2)
        grid.setColumnMinimumWidth(2, 120)
        self._sub_label = QLabel(self._subscriber_text)
        self._sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_label.setObjectName('cardSubs')
        grid.addWidget(self._sub_label, 0, 3)
        grid.setColumnMinimumWidth(3, 130)
        self._review_dot = QLabel('⚠')
        self._review_dot.setFixedWidth(24)
        self._review_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._review_dot.setToolTip('New activity — click to inspect')
        self._review_dot.setObjectName('cardAlert')
        self._review_dot.setVisible(self._has_new_activity)
        grid.addWidget(self._review_dot, 0, 4)
        grid.setColumnMinimumWidth(4, 24)
        # Sparkline (activity dots)
        self._sparkline = _SparklineWidget(self._activity_data, self)
        grid.addWidget(self._sparkline, 0, 5)
        grid.setColumnMinimumWidth(5, 64)
        self._activity_label = QLabel(relative_time(self._last_activity_iso))
        self._activity_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._activity_label.setObjectName('cardActivity')
        grid.addWidget(self._activity_label, 0, 6)
        grid.setColumnMinimumWidth(6, 140)
        date_added = self._creator.get('date_added', '')
        self._duration_label = QLabel(membership_duration(date_added))
        self._duration_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._duration_label.setObjectName('cardActivity')
        grid.addWidget(self._duration_label, 0, 7)
        grid.setColumnMinimumWidth(7, 90)
        # Tags row (always placed in the grid; shown only when there are tags
        # so refresh_tags() can reveal it later without touching the layout).
        self._tags_row = QWidget(self)
        tags_layout = QHBoxLayout(self._tags_row)
        tags_layout.setContentsMargins(0, 0, 0, 0)
        tags_layout.setSpacing(4)
        tags_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self._tags_row, 1, 0, 1, 8)
        self._render_tags()
    def _render_tags(self) -> None:
        """Rebuild the tag chips from the creator's current ``tags`` value.

        Clears ``self._tags_row`` and repopulates it, hiding the row when
        there are no tags.  Called at construction and after any tag edit.
        """
        layout = self._tags_row.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        try:
            tags = json.loads(self._creator.get('tags', '[]'))
        except (json.JSONDecodeError, TypeError):
            tags = []
        for tag in tags:
            chip = QLabel(tag)
            chip.setObjectName('tagChip')
            layout.addWidget(chip)
        self._tags_row.setVisible(bool(tags))
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
                    shadow_color = QColor(C.ACCENT)
                    shadow_color.setAlpha(new_alpha)
                    self._shadow.setColor(shadow_color)
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
        edit_nick = QAction('Edit Nickname', self)
        edit_nick.triggered.connect(lambda: self.edit_requested.emit(self._creator['id'], 'nickname', self._creator.get('nickname', '')))
        menu.addAction(edit_nick)
        edit_plat = QAction('Edit Platforms', self)
        edit_plat.triggered.connect(lambda: self.edit_requested.emit(self._creator['id'], 'platforms', self._creator.get('platforms', '[]')))
        menu.addAction(edit_plat)
        edit_date = QAction('Edit Date Added', self)
        edit_date.triggered.connect(lambda: self.edit_requested.emit(self._creator['id'], 'date_added', self._creator.get('date_added', '')))
        menu.addAction(edit_date)
        # Change Role submenu
        if self._roles:
            role_menu = QMenu('Change Role', self)
            current_role_id = self._creator.get('role_id')
            for r in self._roles:
                action = role_menu.addAction(r['role_name'])
                action.setCheckable(True)
                action.setChecked(r['id'] == current_role_id)
                rid = r['id']
                action.triggered.connect(lambda checked, rid=rid: self.role_change_requested.emit(self._creator['id'], rid))
            menu.addMenu(role_menu)
        # Manage Tags
        manage_tags = QAction('Manage Tags', self)
        manage_tags.triggered.connect(lambda: self._manage_tags())
        menu.addAction(manage_tags)
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

    def _manage_tags(self) -> None:
        """Open a dialog to manage tags for this creator."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QListWidget, QListWidgetItem, QDialogButtonBox
        from ui.theme.stylesheet import build_dialog_qss
        dlg = QDialog(self)
        dlg.setWindowTitle(f'Manage Tags — {self._creator.get("nickname", "Unknown")}')
        dlg.setMinimumWidth(300)
        dlg.setStyleSheet(build_dialog_qss())
        layout = QVBoxLayout(dlg)
        try:
            current_tags = json.loads(self._creator.get('tags', '[]'))
        except (json.JSONDecodeError, TypeError):
            current_tags = []
        tag_list = QListWidget()
        for tag in current_tags:
            item = QListWidgetItem(tag)
            item.setData(Qt.ItemDataRole.UserRole, tag)
            tag_list.addItem(item)
        layout.addWidget(tag_list)
        remove_btn = QPushButton('Remove Selected')
        remove_btn.clicked.connect(lambda: [tag_list.takeItem(tag_list.row(item)) for item in tag_list.selectedItems()])
        layout.addWidget(remove_btn)
        add_row = QHBoxLayout()
        add_input = QLineEdit()
        add_input.setPlaceholderText('Add tag…')
        add_row.addWidget(add_input, 1)
        add_btn = QPushButton('Add')
        add_btn.clicked.connect(lambda: add_input.text().strip() and (
            tag_list.addItem(QListWidgetItem(add_input.text().strip())),
            add_input.clear()
        ))
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_tags = [tag_list.item(i).data(Qt.ItemDataRole.UserRole) or tag_list.item(i).text() for i in range(tag_list.count())]
            # Find the DatabaseManager via the parent chain
            from core.db_manager import DatabaseManager
            db = None
            parent_widget = self.parent()
            while parent_widget:
                if hasattr(parent_widget, '_db') and isinstance(parent_widget._db, DatabaseManager):
                    db = parent_widget._db
                    break
                parent_widget = parent_widget.parent()
            if db:
                db.set_creator_tags(self._creator['id'], new_tags)
                self._creator['tags'] = json.dumps(new_tags)
                self.tags_changed.emit(self._creator['id'])

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self._focused = True
        self.setStyleSheet(card_stylesheet(
            self._role.get('role_color') if self._role else None,
            focused=True,
        ))

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self._focused = False
        self.setStyleSheet(card_stylesheet(
            self._role.get('role_color') if self._role else None,
            focused=False,
        ))

    def reapply_theme(self) -> None:
        """Re-apply token-driven styling after a theme switch (in place).

        The card frame uses the dynamic ``card_stylesheet`` (role colour is a
        runtime value), so it must be rebuilt here. Child labels are styled by
        object-name rules in the global stylesheet and update automatically;
        the sparkline repaints from the live accent on its next paint.
        """
        if sip.isdeleted(self):
            return
        self.setStyleSheet(card_stylesheet(
            self._role.get('role_color') if self._role else None,
            focused=self._focused,
        ))
        self._sparkline.update()
        # Re-color the trend glyph from live theme tokens.
        self._refresh_trend_label()
        self.update()

    # ── Subscriber trend arrow ────────────────────────────────────────

    _TREND_GLYPH = {'up': '▲', 'down': '▼', 'flat': '◆', 'none': ''}
    _TREND_COLOR = {'up': 'SUCCESS', 'down': 'DANGER', 'flat': 'TEXT_MUTED', 'none': 'TEXT_MUTED'}
    _TREND_TIP = {
        'up': 'Subscribers trending up over the last week',
        'down': 'Subscribers trending down over the last week',
        'flat': 'Subscriber count stable over the last week',
        'none': 'No trend data yet',
    }

    def set_trend(self, arrow: str) -> None:
        """Set the subscriber trend arrow ('up'|'down'|'flat'|'none')."""
        self._trend = arrow if arrow in ('up', 'down', 'flat', 'none') else 'none'
        self._refresh_trend_label()

    def _refresh_trend_label(self) -> None:
        """Render the trend glyph as a coloured suffix on the subscriber label.

        Uses rich text so the glyph can take a trend-specific colour while the
        subscriber count keeps the ``cardSubs`` stylesheet colour. Re-reads the
        colour token each call so a theme switch recolours the glyph in place.
        """
        if sip.isdeleted(self) or not hasattr(self, '_sub_label'):
            return
        glyph = self._TREND_GLYPH.get(self._trend, '')
        if not glyph:
            self._sub_label.setTextFormat(Qt.TextFormat.PlainText)
            self._sub_label.setText(self._subscriber_text)
            self._sub_label.setToolTip('')
            return
        color_attr = self._TREND_COLOR.get(self._trend, 'TEXT_MUTED')
        color = getattr(C, color_attr, C.TEXT_MUTED)
        self._sub_label.setTextFormat(Qt.TextFormat.RichText)
        self._sub_label.setText(
            f'{self._subscriber_text} <span style="color:{color};"> {glyph}</span>'
        )
        self._sub_label.setToolTip(self._TREND_TIP.get(self._trend, ''))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
            self.clicked.emit(self._creator['id'])
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._navigate_card(event.key())
            event.accept()
            return
        super().keyPressEvent(event)

    def _navigate_card(self, key: int) -> None:
        """Move focus to the previous/next visible CreatorCard in the layout."""
        parent_layout = self.parent()
        if parent_layout is None:
            return
        layout = parent_layout.layout() if hasattr(parent_layout, 'layout') else None
        if layout is None:
            # Walk up to find a layout
            widget = parent_layout
            while widget is not None:
                if widget.layout() is not None:
                    layout = widget.layout()
                    break
                widget = widget.parent()
        if layout is None:
            return
        # Collect visible CreatorCard siblings in layout order
        siblings = []
        for i in range(layout.count()):
            item = layout.itemAt(i)
            w = item.widget() if item is not None else None
            if isinstance(w, CreatorCard) and w.isVisible() and not w.isHidden():
                siblings.append(w)
        if not siblings:
            return
        try:
            idx = siblings.index(self)
        except ValueError:
            return
        direction = -1 if key == Qt.Key.Key_Up else 1
        new_idx = (idx + direction) % len(siblings)
        target = siblings[new_idx]
        target.setFocus()
        # Scroll the scroll area to make the target visible
        scroll = target
        while scroll is not None:
            from PyQt6.QtWidgets import QScrollArea
            if isinstance(scroll, QScrollArea):
                scroll.ensureWidgetVisible(target)
                break
            scroll = scroll.parent()

    def update_data(self, creator: dict, role: dict | None, last_activity: str, has_new_activity: bool, subscriber_text: str, roles: list | None = None, activity_data: list[int] | None = None, trend: str | None = None) -> None:
        """Update this card's data in-place without destroying/recreating the widget."""
        self._creator = creator
        self._role = role
        self._last_activity_iso = last_activity
        self._has_new_activity = has_new_activity
        self._subscriber_text = subscriber_text
        if roles is not None:
            self._roles = roles
        # Update visible widgets
        self._name_label.setText(creator.get('nickname', 'Unknown'))
        self._activity_label.setText(relative_time(last_activity))
        self._review_dot.setVisible(has_new_activity)
        self._load_avatar()
        if activity_data is not None:
            self._sparkline.update_data(activity_data)
        if trend is not None:
            self.set_trend(trend)
        else:
            self._refresh_trend_label()
        # Update role color stylesheet
        role_color = role.get('role_color') if role else None
        self.setStyleSheet(card_stylesheet(role_color))
        # Update tags row
        self._render_tags()

    def refresh_tags(self) -> None:
        """Rebuild tag chips from the current creator record (no data reload).

        Use after the creator's ``tags`` field has been mutated in place,
        e.g. from the tag-management dialog, to refresh the chips without a
        full card rebuild.
        """
        self._render_tags()
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