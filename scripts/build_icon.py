"""One-time script to generate assets/icon.ico from the red triangle design.

Run this whenever the icon design changes:
    python scripts/build_icon.py

Requires PyQt6 and Pillow (both are already project dependencies).
"""

import sys
import os

# Ensure the project root is on the path so `ui.app_icon` can be imported.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPolygonF
from PyQt6.QtWidgets import QApplication
from PIL import Image


def _render_triangle(size: int) -> QImage:
    """Render the red triangle at the given square size onto a transparent QImage."""
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

    return img


def _save_png(img: QImage, path: str) -> None:
    """Save a QImage as PNG."""
    img.save(path, 'PNG')


def main() -> None:
    # Qt needs a QApplication for image operations
    app = QApplication.instance() or QApplication(sys.argv)

    sizes = [16, 32, 48, 256]
    png_paths: list[str] = []

    tmp_dir = os.path.join(os.path.dirname(__file__), '..', 'assets')
    os.makedirs(tmp_dir, exist_ok=True)

    for s in sizes:
        png_path = os.path.join(tmp_dir, f'icon_{s}.png')
        img = _render_triangle(s)
        _save_png(img, png_path)
        png_paths.append(png_path)
        print(f'  Wrote {png_path}')

    # Combine PNGs into a single .ico using Pillow
    ico_path = os.path.join(tmp_dir, 'icon.ico')
    pil_images = []
    for p in png_paths:
        img = Image.open(p)
        img.load()  # force-read so the file handle can close
        pil_images.append(img)
    pil_images[0].save(ico_path, format='ICO', sizes=[(s, s) for s in sizes])
    print(f'  Wrote {ico_path}')

    # Close images before deleting temp PNGs
    for img in pil_images:
        img.close()
    for p in png_paths:
        try:
            os.remove(p)
        except OSError:
            pass

    print('Done.')


if __name__ == '__main__':
    main()