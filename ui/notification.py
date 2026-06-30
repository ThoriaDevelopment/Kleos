"""Toast notification widget for the Kleos UI.

A ``NotificationToast`` is a small card that slides in from the top-right of
the parent window, stays visible for a configurable duration, then fades out
and self-destructs.  Multiple toasts stack vertically without overlapping.
"""
from __future__ import annotations

from PyQt6.QtCore import (
    QPropertyAnimation,
    QRect,
    Qt,
    pyqtSignal,
    QTimer,
)
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.theme.tokens import C


# Keep track of active toasts so they stack correctly.
_active_toasts: list[NotificationToast] = []


class NotificationToast(QFrame):
    """A small toast notification that slides in from the top-right and auto-dismisses.

    Usage::

        toast = NotificationToast("Upload complete", "3 new videos verified.", parent_window)
        toast.show()

    The toast positions itself relative to *parent*'s top-right corner.  If
    other toasts are already visible it will stack below them.
    """

    closed = pyqtSignal()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def __init__(
        self,
        title: str,
        message: str,
        parent: QWidget,
        duration_ms: int = 5000,
    ) -> None:
        super().__init__(parent)
        self._duration_ms = duration_ms
        self._is_dismissing = False

        self.setObjectName('notificationToast')
        self.setWindowFlags(Qt.WindowType.SubWindow)  # stays inside the parent
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(320)
        self.setMinimumHeight(0)

        # ---- Layout ----
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        card = QFrame(self)
        card.setObjectName('toastCard')
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 10, 14, 12)
        card_layout.setSpacing(4)

        # Title row (title + close button)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)

        title_lbl = QLabel(title)
        title_lbl.setObjectName('toastTitle')
        title_row.addWidget(title_lbl)

        title_row.addStretch()

        close_btn = QPushButton('×')  # ×
        close_btn.setObjectName('toastCloseBtn')
        close_btn.setFixedSize(22, 22)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.dismiss)
        title_row.addWidget(close_btn)

        card_layout.addLayout(title_row)

        # Message
        msg_lbl = QLabel(message)
        msg_lbl.setObjectName('toastMessage')
        msg_lbl.setWordWrap(True)
        card_layout.addWidget(msg_lbl)

        outer.addWidget(card)

        # ---- Auto-dismiss timer ----
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        if duration_ms > 0:
            self._timer.start(duration_ms)

        # Opacity for fade-out
        self._opacity = 1.0

    # ------------------------------------------------------------------
    # Show / positioning
    # ------------------------------------------------------------------
    def show(self) -> None:  # noqa: D401 — override QWidget.show
        """Show the toast with a slide-in animation, stacking below others."""
        super().show()
        # Force layout computation before positioning.
        self.adjustSize()

        parent_rect = self.parentWidget().rect() if self.parentWidget() else QRect(0, 0, 800, 600)
        margin = 12

        # Calculate the Y position based on existing toasts.
        y_offset = margin
        for t in _active_toasts:
            if t is not self and t.isVisible():
                y_offset += t.height() + 8  # 8px gap between toasts

        target_x = parent_rect.width() - self.width() - margin
        target_y = y_offset

        # Start off-screen to the right for slide-in.
        start_x = parent_rect.width() + 20
        start_y = target_y

        self.move(start_x, start_y)

        # Slide-in animation
        self._slide_anim = QPropertyAnimation(self, b'pos')
        self._slide_anim.setDuration(250)
        self._slide_anim.setStartValue(QRect(start_x, start_y, self.width(), self.height()))
        self._slide_anim.setEndValue(QRect(target_x, target_y, self.width(), self.height()))
        self._slide_anim.start()

        _active_toasts.append(self)

    # ------------------------------------------------------------------
    # Dismiss / fade-out
    # ------------------------------------------------------------------
    def dismiss(self) -> None:
        """Start fade-out and then close the toast."""
        if self._is_dismissing:
            return
        self._is_dismissing = True
        self._timer.stop()

        # Fade-out via opacity animation
        self._fade_anim = QPropertyAnimation(self, b'windowOpacity')
        self._fade_anim.setDuration(200)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self._on_fade_out_done)
        self._fade_anim.start()

    def _on_fade_out_done(self) -> None:
        """Clean up after fade-out completes."""
        self.hide()
        self.close()
        self.closed.emit()
        if self in _active_toasts:
            _active_toasts.remove(self)
        self.deleteLater()

    # ------------------------------------------------------------------
    # Paint (for opacity support)
    # ------------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802 — Qt naming
        painter = QPainter(self)
        painter.setOpacity(self.windowOpacity())
        painter.setBrush(QColor(C.BG_RAISED))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 8, 8)
        painter.end()
        super().paintEvent(event)