from __future__ import annotations
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygonF
def create_app_icon() -> QIcon:
    """Return a QIcon with a crisp red triangle, generated at runtime."""
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor('transparent'))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor('#FF3B30'))
    painter.setPen(QColor('transparent'))
    triangle = QPolygonF([QPointF(16.0, 4.0), QPointF(4.0, 28.0), QPointF(28.0, 28.0)])
    painter.drawPolygon(triangle)
    painter.end()
    return QIcon(pixmap)