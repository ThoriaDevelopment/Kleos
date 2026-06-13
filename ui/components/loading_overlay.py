"""Semi-transparent loading overlay with spinning ring animation.

Usage::

    overlay = LoadingOverlay(parent_widget, text='Loading...')
    overlay.show()   # shows the spinner over the parent widget
    overlay.hide()   # removes it
"""
from __future__ import annotations
from PyQt6.QtCore import QPropertyAnimation, QTimer, Qt, pyqtProperty
from PyQt6.QtGui import QPainter, QPen, QColor
from PyQt6.QtWidgets import QWidget
from ui.theme.tokens import C


class LoadingOverlay(QWidget):
    """A semi-transparent overlay with a spinning ring and optional text.

    Place over any widget to indicate a loading state.  The overlay
    automatically resizes to cover its parent and shows a spinning ring
    animation in the center.
    """

    def __init__(self, parent: QWidget, text: str = 'Loading...') -> None:
        super().__init__(parent)
        self._text = text
        self._angle = 0
        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(30)  # ~33 fps
        self._animation_timer.timeout.connect(self._tick)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.hide()

    def _tick(self) -> None:
        self._angle = (self._angle + 6) % 360
        self.update()

    def show(self) -> None:
        """Show the overlay and start the animation."""
        if self.parent():
            self.setGeometry(self.parent().rect())
        self._animation_timer.start()
        super().show()
        self.raise_()
        self.update()

    def hide(self) -> None:
        """Hide the overlay and stop the animation."""
        self._animation_timer.stop()
        super().hide()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Semi-transparent background
        painter.fillRect(self.rect(), QColor(0, 0, 0, 140))

        # Spinning ring
        center_x = self.width() // 2
        center_y = self.height() // 2 - 20
        radius = 24

        pen = QPen(QColor(C.ACCENT), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(
            center_x - radius, center_y - radius,
            radius * 2, radius * 2,
            self._angle * 16, 270 * 16,
        )

        # Faint track ring
        track_pen = QPen(QColor(C.BG_HOVER), 2)
        painter.setPen(track_pen)
        painter.drawArc(
            center_x - radius, center_y - radius,
            radius * 2, radius * 2,
            0, 360 * 16,
        )

        # Text label
        painter.setPen(QColor(C.TEXT_PRIMARY))
        painter.setFont(self.font())
        painter.drawText(
            self.rect().adjusted(0, center_y + radius + 10, 0, 0),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            self._text,
        )
        painter.end()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.isVisible() and self.parent():
            self.setGeometry(self.parent().rect())