from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QMessageBox, QWidget
_DARK_QSS = 'QMessageBox { background: #1A1A1A; }QMessageBox QLabel { color: #E0E0E0; background: transparent; }QPushButton { background: #2E2E2E; color: #E0E0E0; border: 1px solid #3A3A3A; border-radius: 4px; padding: 6px 14px; }QPushButton:hover { background: #4A4A4A; }'


def toggle_fullscreen(window: QWidget) -> None:
    """Toggle a window between normal and fullscreen.

    Uses ``showFullScreen()`` / ``showNormal()`` which is cross-platform
    and works for both ``QMainWindow`` and ``QDialog``.
    """
    if window.isFullScreen():
        window.showNormal()
    else:
        window.showFullScreen()


def handle_fullscreen_keypress(window: QWidget, event: QKeyEvent) -> bool:
    """Process a key event for fullscreen shortcuts.

    Returns ``True`` if the event was handled (F11 toggles, Escape exits
    fullscreen) so the caller can skip further processing.
    """
    if event.key() == Qt.Key.Key_F11:
        toggle_fullscreen(window)
        return True
    if event.key() == Qt.Key.Key_Escape and window.isFullScreen():
        window.showNormal()
        return True
    return False


def enable_window_maximize(window: QWidget) -> None:
    """Add the minimize and maximize buttons to a dialog's title bar.

    Only needed for ``QDialog`` subclasses — ``QMainWindow`` already has
    them by default.
    """
    window.setWindowFlags(
        window.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint
    )


def dark_warning(parent: QWidget, title: str, text: str) -> None:
    """Show a dark-themed warning message box."""
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setStyleSheet(_DARK_QSS)
    msg.exec()
def dark_info(parent: QWidget, title: str, text: str) -> None:
    """Show a dark-themed information message box."""
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Information)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setStyleSheet(_DARK_QSS)
    msg.exec()
def dark_question(parent: QWidget, title: str, text: str, buttons: QMessageBox.StandardButton=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, default: QMessageBox.StandardButton=QMessageBox.StandardButton.No) -> QMessageBox.StandardButton:
    """Show a dark-themed question message box and return the clicked button."""
    if default and not (default & buttons):
        default = QMessageBox.StandardButton.No
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Question)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setStandardButtons(buttons)
    msg.setDefaultButton(default)
    msg.setStyleSheet(_DARK_QSS)
    return msg.exec()