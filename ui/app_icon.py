from __future__ import annotations

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap, QPolygonF


def create_app_icon() -> QIcon:
    """Return a QIcon with a crisp red triangle at multiple resolutions."""
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        pixmap = _render_triangle(size)
        icon.addPixmap(pixmap)
    return icon


def _render_triangle(size: int) -> QPixmap:
    """Render the red triangle at the given pixel size on a transparent background."""
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor('#FF3B30'))
    painter.setPen(QColor('transparent'))

    margin = size * 0.125
    top = QPointF(size / 2, margin)
    left = QPointF(margin, size - margin)
    right = QPointF(size - margin, size - margin)
    painter.drawPolygon(QPolygonF([top, left, right]))
    painter.end()

    return QPixmap.fromImage(img)