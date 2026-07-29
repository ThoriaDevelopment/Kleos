from __future__ import annotations
import sys
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QMessageBox, QWidget

from ui.theme.tokens import C


def apply_native_title_bar(window: QWidget) -> None:
    """Match the Windows native title bar to the active theme via DWM API.

    Dark themes get the immersive dark title bar; light themes get the default
    light title bar so it doesn't clash with a light window background.  Decided
    from the luminance of ``C.BG_BASE``.  No-op off Windows.
    """
    if sys.platform != 'win32':
        return
    import ctypes
    hexcol = (C.BG_BASE or '').lstrip('#')
    dark = True
    if len(hexcol) == 6:
        try:
            r, g, b = (int(hexcol[i:i + 2], 16) for i in (0, 2, 4))
            dark = (0.299 * r + 0.587 * g + 0.114 * b) < 140
        except ValueError:
            dark = True
    hwnd = int(window.winId())
    DWMWA_USE_IMMERSIVE_DARK_MODE = 20
    value = ctypes.c_int(1 if dark else 0)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(
        hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value))


def _msg_qss() -> str:
    """Build a theme-aware QMessageBox stylesheet from the active tokens.

    Previously this was a hardcoded dark string; it is now derived from ``C`` so
    message boxes match the current theme (light or dark) instead of always
    rendering dark over a potentially light window.
    """
    return (
        f'QMessageBox {{ background: {C.DIALOG_BG}; }}'
        f'QMessageBox QLabel {{ color: {C.TEXT_PRIMARY}; background: transparent; }}'
        f'QPushButton {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; '
        f'border: 1px solid {C.BORDER}; border-radius: 4px; padding: 6px 14px; }}'
        f'QPushButton:hover {{ background: {C.BG_HOVER}; }}'
    )


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
    """Add the maximize button to a dialog's title bar.

    Only needed for ``QDialog`` subclasses — ``QMainWindow`` already has
    them by default.  On Windows, ``WindowMinMaxButtonsHint`` also adds a
    minimize button which causes the parent window to minimize as a side-effect,
    so we use only ``WindowMaximizeButtonHint`` instead.
    """
    window.setWindowFlags(
        window.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint
    )


def compact_count(n: int) -> str:
    """Format an integer in compact form: 1200 → '1.2K', 1500000 → '1.5M'.

    Shared by every UI surface that shows subscriber/view counts (creator
    cards, the Discover results, the Candidate Pool) so they don't each
    re-implement the same threshold ladder.
    """
    n = int(n or 0)
    if n >= 1_000_000:
        return f'{n / 1_000_000:.1f}M'
    if n >= 1_000:
        return f'{n / 1_000:.1f}K'
    return str(n)


def dark_warning(parent: QWidget, title: str, text: str) -> None:
    """Show a dark-themed warning message box."""
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setStyleSheet(_msg_qss())
    msg.exec()
def dark_info(parent: QWidget, title: str, text: str) -> None:
    """Show a dark-themed information message box."""
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Information)
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setStyleSheet(_msg_qss())
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
    msg.setStyleSheet(_msg_qss())
    return msg.exec()