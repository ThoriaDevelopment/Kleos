"""Kleos global stylesheet builder.

Produces a single QSS string from the design-system tokens so that
every widget class shares one consistent source of truth for colours,
spacing, and typography.
"""

from __future__ import annotations
from PyQt6.QtWidgets import QApplication, QDialog
from .tokens import C, M


def build_global_qss() -> str:
    """Return the application-wide stylesheet string.

    Call once at startup and apply via ``app.setStyleSheet(...)``.
    Individual dialogs and widgets may layer additional QSS on top,
    but the base palette lives here.
    """
    return (
        f'QMainWindow {{ background: {C.BG_BASE}; }}\n'
        f'QWidget#centralWidget {{ background: transparent; }}\n'
        f'QScrollArea {{ border: none; background: transparent; }}\n'
        f'QScrollArea > QWidget {{ background: transparent; }}\n'
        f'QAbstractItemView {{ background: {C.BG_LAYER}; }}\n'
        f'QMenu {{ background-color: {C.BG_RAISED}; border: 1px solid {C.BORDER}; }}\n'
        f'QMenu::item {{ color: {C.TEXT_PRIMARY}; padding: 6px 20px; }}\n'
        f'QMenu::item:selected {{ background-color: {C.BG_HOVER}; color: {C.TEXT_PRIMARY}; }}\n'
        f'QMenu::item:pressed {{ background-color: {C.BG_PRESS}; color: {C.TEXT_PRIMARY}; }}\n'
        f'QPushButton {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; border-radius: 6px; padding: 6px 14px; }}\n'
        f'QPushButton:hover {{ background: {C.BG_HOVER}; }}\n'
        f'QPushButton:pressed {{ background: {C.BG_PRESS}; }}\n'
        f'QLineEdit {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.INPUT_BORDER}; border-radius: 4px; padding: 4px 8px; }}\n'
        f'QComboBox {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.INPUT_BORDER}; border-radius: 4px; padding: 4px 8px; }}\n'
        f'QComboBox::drop-down {{ border: none; }}\n'
        f'QComboBox QAbstractItemView {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; selection-background-color: {C.BG_HOVER}; }}\n'
        f'QLabel {{ color: {C.TEXT_PRIMARY}; }}\n'
        f'QCheckBox {{ color: {C.TEXT_PRIMARY}; }}\n'
        f'QCheckBox::indicator {{ width: 16px; height: 16px; background: {C.INPUT_BG}; border: 1px solid {C.INPUT_BORDER}; border-radius: 3px; }}\n'
        f'QCheckBox::indicator:checked {{ background: {C.ACCENT}; border: 1px solid {C.ACCENT}; }}\n'
        f'QListWidget {{ background: {C.BG_LAYER}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; border-radius: 6px; }}\n'
        f'QListWidget::item:selected {{ background: {C.BG_HOVER}; }}\n'
        f'QDialog {{ background: {C.BG_BASE}; }}\n'
        f'QFormLayout QLabel {{ color: {C.TEXT_SECONDARY}; padding: 4px 0; }}\n'
        f'QCalendarWidget {{ background: {C.BG_LAYER}; color: {C.TEXT_PRIMARY}; }}\n'
        f'QCalendarWidget QToolButton {{ color: {C.TEXT_PRIMARY}; background: {C.BG_RAISED}; border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px; }}\n'
        f'QCalendarWidget QAbstractItemView {{ background: {C.BG_LAYER}; color: {C.TEXT_PRIMARY}; selection-background-color: {C.ACCENT}; selection-color: {C.TEXT_ON_ACCENT}; }}\n'
        f'QProgressBar {{ background: {C.BG_RAISED}; border: 1px solid {C.BORDER}; border-radius: 4px; text-align: center; color: {C.TEXT_PRIMARY}; }}\n'
        f'QProgressBar::chunk {{ background: {C.ACCENT}; border-radius: 3px; }}\n'
        f'QToolTip {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; padding: 4px 8px; border-radius: 4px; }}\n'
    )


def build_dialog_qss() -> str:
    """Return a QSS string for QDialog subclasses using design tokens.

    This provides a complete, consistent dark theme for all dialog windows.
    Call once in each dialog's __init__ and apply via setStyleSheet().
    """
    return (
        f'QDialog {{ background: {C.DIALOG_BG}; }}\n'
        f'QLabel {{ color: {C.TEXT_PRIMARY}; background: transparent; }}\n'
        f'QLineEdit {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.INPUT_BORDER}; border-radius: 4px; padding: 4px 8px; }}\n'
        f'QLineEdit:focus {{ border-color: {C.ACCENT}; }}\n'
        f'QTextEdit {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.INPUT_BORDER}; border-radius: 4px; padding: 4px 8px; }}\n'
        f'QTextEdit:focus {{ border-color: {C.ACCENT}; }}\n'
        f'QComboBox {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.INPUT_BORDER}; border-radius: 4px; padding: 4px 8px; }}\n'
        f'QComboBox::drop-down {{ border: none; }}\n'
        f'QComboBox QAbstractItemView {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; selection-background-color: {C.BG_HOVER}; }}\n'
        f'QPushButton {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; border-radius: 4px; padding: 6px 14px; }}\n'
        f'QPushButton:hover {{ background: {C.BG_HOVER}; }}\n'
        f'QPushButton:pressed {{ background: {C.BG_PRESS}; }}\n'
        f'QPushButton:checked {{ background: {C.ACCENT}; border-color: {C.ACCENT}; color: {C.TEXT_ON_ACCENT}; }}\n'
        f'QScrollArea {{ border: none; background: transparent; }}\n'
        f'QScrollArea > QWidget {{ background: transparent; }}\n'
        f'QScrollBar:vertical {{ background: {C.BG_LAYER}; width: 8px; border-radius: 4px; }}\n'
        f'QScrollBar::handle:vertical {{ background: {C.BG_HOVER}; border-radius: 4px; min-height: 20px; }}\n'
        f'QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}\n'
        f'QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}\n'
        f'QFrame {{ border: none; }}\n'
        f'QMenu {{ background-color: {C.BG_RAISED}; border: 1px solid {C.BORDER}; }}\n'
        f'QMenu::item {{ color: {C.TEXT_PRIMARY}; padding: 6px 20px; }}\n'
        f'QMenu::item:selected {{ background-color: {C.BG_HOVER}; }}\n'
        f'QMenu::separator {{ height: 1px; background: {C.BORDER}; margin: 4px 10px; }}\n'
        f'QTabWidget::pane {{ border: 1px solid {C.BORDER}; background: {C.DIALOG_BG}; }}\n'
        f'QTabBar::tab {{ background: {C.BG_RAISED}; color: {C.TEXT_SECONDARY}; padding: 6px 16px; border: 1px solid {C.BORDER}; border-bottom: none; border-radius: 4px 4px 0 0; margin-right: 2px; }}\n'
        f'QTabBar::tab:selected {{ background: {C.DIALOG_BG}; color: {C.TEXT_PRIMARY}; border-bottom: 2px solid {C.ACCENT}; }}\n'
        f'QCheckBox {{ color: {C.TEXT_PRIMARY}; spacing: 6px; }}\n'
        f'QCheckBox::indicator {{ width: 16px; height: 16px; background: {C.INPUT_BG}; border: 1px solid {C.INPUT_BORDER}; border-radius: 3px; }}\n'
        f'QCheckBox::indicator:checked {{ background: {C.ACCENT}; border: 1px solid {C.ACCENT}; }}\n'
        f'QProgressBar {{ background: {C.BG_RAISED}; border: 1px solid {C.BORDER}; border-radius: 4px; text-align: center; color: {C.TEXT_PRIMARY}; }}\n'
        f'QProgressBar::chunk {{ background: {C.ACCENT}; border-radius: 3px; }}\n'
        f'QListWidget {{ background: {C.BG_LAYER}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; border-radius: 4px; }}\n'
        f'QListWidget::item:selected {{ background: {C.BG_HOVER}; }}\n'
        f'QListWidget::item:hover {{ background: {C.BG_HOVER}; }}\n'
        f'QSpinBox {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.INPUT_BORDER}; border-radius: 4px; padding: 4px 8px; }}\n'
        f'QDialogButtonBox QPushButton {{ min-width: 80px; }}\n'
        f'QToolTip {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; padding: 4px 8px; border-radius: 4px; }}\n'
    )


def refresh_all_styles() -> None:
    """Re-apply global and dialog stylesheets after a theme change.

    Call this after ``theme_manager.apply()`` to push the new colour
    tokens into every open widget.
    """
    app = QApplication.instance()
    if app:
        app.setStyleSheet(build_global_qss())
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, QDialog):
            widget.setStyleSheet(build_dialog_qss())
