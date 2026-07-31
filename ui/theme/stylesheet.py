"""Kleos global stylesheet builder.

Produces QSS strings from the design-system tokens so that every widget
class shares one consistent source of truth for colours, spacing, and
typography. Object-name-keyed rules (``#card``, ``#accentPrimary``, ...)
let widgets drop their inline ``setStyleSheet`` f-strings and pick up
theme changes live via :func:`refresh_all_styles`.
"""

from __future__ import annotations

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QDialog, QGraphicsDropShadowEffect, QWidget
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
        f'QAbstractItemView {{ background: {C.BG_LAYER}; color: {C.TEXT_PRIMARY}; gridline-color: {C.BORDER}; }}\n'
        f'QHeaderView {{ background: {C.BG_RAISED}; }}\n'
        f'QHeaderView::section {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; padding: 4px 8px; border: none; border-right: 1px solid {C.BORDER}; border-bottom: 1px solid {C.BORDER}; }}\n'
        f'QTableCornerButton::section {{ background: {C.BG_RAISED}; border: none; }}\n'
        f'QRadioButton {{ color: {C.TEXT_PRIMARY}; spacing: 6px; }}\n'
        f'QGroupBox {{ color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; border-radius: {M.RADIUS_MD}px; margin-top: 10px; padding-top: 6px; }}\n'
        f'QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {C.TEXT_SECONDARY}; }}\n'
        f'QMenu {{ background-color: {C.BG_RAISED}; border: 1px solid {C.BORDER}; }}\n'
        f'QMenu::item {{ color: {C.TEXT_PRIMARY}; padding: {M.SPACE_SM}px {M.SPACE_XL}px; }}\n'
        f'QMenu::item:selected {{ background-color: {C.BG_HOVER}; color: {C.TEXT_PRIMARY}; }}\n'
        f'QMenu::item:pressed {{ background-color: {C.BG_PRESS}; color: {C.TEXT_PRIMARY}; }}\n'
        f'QPushButton {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; border-radius: {M.RADIUS_LG}px; padding: {M.SPACE_SM}px {M.SPACE_LG}px; }}\n'
        f'QPushButton:hover {{ background: {C.BG_HOVER}; }}\n'
        f'QPushButton:pressed {{ background: {C.BG_PRESS}; }}\n'
        f'QLineEdit {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.INPUT_BORDER}; border-radius: {M.RADIUS_MD}px; padding: {M.SPACE_XS}px {M.SPACE_MD}px; }}\n'
        f'QComboBox {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.INPUT_BORDER}; border-radius: {M.RADIUS_MD}px; padding: {M.SPACE_XS}px {M.SPACE_MD}px; }}\n'
        f'QComboBox::drop-down {{ border: none; }}\n'
        f'QComboBox QAbstractItemView {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; selection-background-color: {C.BG_HOVER}; }}\n'
        f'QLabel {{ color: {C.TEXT_PRIMARY}; }}\n'
        f'QCheckBox {{ color: {C.TEXT_PRIMARY}; }}\n'
        f'QCheckBox::indicator {{ width: 16px; height: 16px; background: {C.INPUT_BG}; border: 1px solid {C.INPUT_BORDER}; border-radius: {M.RADIUS_SM}px; }}\n'
        f'QCheckBox::indicator:checked {{ background: {C.ACCENT}; border: 1px solid {C.ACCENT}; }}\n'
        f'QListWidget {{ background: {C.BG_LAYER}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; border-radius: {M.RADIUS_LG}px; }}\n'
        f'QListWidget::item:selected {{ background: {C.BG_HOVER}; }}\n'
        f'QDialog {{ background: {C.BG_BASE}; }}\n'
        f'QFormLayout QLabel {{ color: {C.TEXT_SECONDARY}; padding: {M.SPACE_XS}px 0; }}\n'
        f'QCalendarWidget {{ background: {C.BG_LAYER}; color: {C.TEXT_PRIMARY}; }}\n'
        f'QCalendarWidget QToolButton {{ color: {C.TEXT_PRIMARY}; background: {C.BG_RAISED}; border: 1px solid {C.BORDER}; border-radius: {M.RADIUS_SM}px; padding: {M.SPACE_XS}px {M.SPACE_MD}px; }}\n'
        f'QCalendarWidget QAbstractItemView {{ background: {C.BG_LAYER}; color: {C.TEXT_PRIMARY}; selection-background-color: {C.ACCENT}; selection-color: {C.TEXT_ON_ACCENT}; }}\n'
        f'QProgressBar {{ background: {C.BG_RAISED}; border: 1px solid {C.BORDER}; border-radius: {M.RADIUS_MD}px; text-align: center; color: {C.TEXT_PRIMARY}; }}\n'
        f'QProgressBar::chunk {{ background: {C.ACCENT}; border-radius: {M.RADIUS_SM}px; }}\n'
        f'QToolTip {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; padding: {M.SPACE_XS}px {M.SPACE_MD}px; border-radius: {M.RADIUS_MD}px; }}\n'
        f'QLabel#chartTooltip {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; padding: {M.SPACE_XS}px {M.SPACE_MD}px; border-radius: {M.RADIUS_MD}px; }}\n'
        # ── Object-name-keyed surfaces (consumed by the inline-QSS migration) ──
        f'QLabel#muted {{ color: {C.TEXT_MUTED}; background: transparent; }}\n'
        f'QLabel#sectionHeader {{ color: {C.TEXT_SECONDARY}; font-size: 12px; font-weight: bold; background: transparent; }}\n'
        f'QLabel#dialogTitle {{ font-size: 16px; font-weight: bold; color: {C.TEXT_PRIMARY}; background: transparent; }}\n'
        f'QLabel#formLabel {{ font-weight: bold; background: transparent; }}\n'
        f'QLabel#hintLabel {{ color: {C.TEXT_MUTED}; font-size: 11px; background: transparent; }}\n'
        f'QLabel#countLabel {{ color: {C.TEXT_SECONDARY}; font-size: 11px; background: transparent; }}\n'
        f'QLabel#noteLabel {{ color: {C.INPUT_PLACEHOLDER}; font-size: 11px; background: transparent; }}\n'
        f'QLabel#accentLabel {{ font-weight: bold; color: {C.ACCENT}; background: transparent; }}\n'
        f'QLabel#wordCount {{ font-size: 11px; background: transparent; color: {C.TEXT_MUTED}; }}\n'
        f'QLabel#wordCount[over="true"] {{ color: {C.DANGER}; }}\n'
        f'QPushButton#accentPrimary {{ background: {C.ACCENT}; color: {C.TEXT_ON_ACCENT}; border: 1px solid {C.ACCENT}; border-radius: {M.RADIUS_MD}px; padding: {M.SPACE_SM}px {M.SPACE_LG}px; }}\n'
        f'QPushButton#accentPrimary:hover {{ background: {C.ACCENT_HOVER}; border-color: {C.ACCENT_HOVER}; }}\n'
        f'QPushButton#accentPrimary:pressed {{ background: {C.ACCENT_PRESS}; }}\n'
        f'QPushButton#accentPrimary:disabled {{ background: {C.BG_RAISED}; color: {C.TEXT_MUTED}; border-color: {C.BORDER}; }}\n'
        f'QPushButton#danger {{ background: {C.DANGER_RED_BG}; color: {C.DANGER}; border: 1px solid {C.DANGER_RED_BORDER}; border-radius: {M.RADIUS_MD}px; padding: {M.SPACE_SM}px {M.SPACE_LG}px; }}\n'
        f'QPushButton#danger:hover {{ background: {C.DANGER}; color: {C.TEXT_ON_ACCENT}; border-color: {C.DANGER}; }}\n'
        f'QPushButton#ghost {{ background: transparent; color: {C.TEXT_SECONDARY}; border: 1px solid {C.BORDER}; border-radius: {M.RADIUS_MD}px; padding: {M.SPACE_SM}px {M.SPACE_LG}px; }}\n'
        f'QPushButton#ghost:hover {{ background: {C.BG_HOVER}; color: {C.TEXT_PRIMARY}; }}\n'
        f'QFrame#card {{ background: {C.CARD_BG}; border: 1px solid {C.BORDER}; border-radius: {M.RADIUS_LG}px; }}\n'
        f'QLabel#cardName {{ color: {C.TEXT_PRIMARY}; font-weight: bold; background: transparent; }}\n'
        f'QLabel#cardPlatformTag {{ background: {C.BG_HOVER}; border-radius: 4px; padding: 2px 10px; font-size: 11px; color: {C.TEXT_SECONDARY}; }}\n'
        f'QLabel#cardSubs {{ color: {C.TEXT_SECONDARY}; font-size: 11px; background: transparent; }}\n'
        f'QLabel#cardActivity {{ color: {C.TEXT_PRIMARY}; font-size: 11px; background: transparent; }}\n'
        f'QLabel#cardAlert {{ color: {C.DANGER}; font-size: 16px; background: transparent; }}\n'
        f'QLabel#cardMeta {{ color: {C.TEXT_SECONDARY}; background: transparent; }}\n'
        f'QLabel#trendArrow {{ background: transparent; }}\n'
        f'QLabel#tagChip {{ background: {C.ACCENT}; color: {C.TEXT_ON_ACCENT}; border-radius: 8px; padding: 1px 6px; font-size: 10px; }}\n'
        f'QDialog#commandPalette {{ background: {C.DIALOG_BG}; border: 1px solid {C.BORDER}; }}\n'
        # ── Toast notifications ──
        f'QFrame#toastCard {{ background: {C.BG_RAISED}; border: 1px solid {C.BORDER}; border-radius: 8px; }}\n'
        f'QLabel#toastTitle {{ font-weight: bold; font-size: 13px; color: {C.TEXT_PRIMARY}; background: transparent; }}\n'
        f'QLabel#toastMessage {{ font-size: 12px; color: {C.TEXT_SECONDARY}; background: transparent; }}\n'
        f'QPushButton#toastCloseBtn {{ background: transparent; color: {C.TEXT_MUTED}; border: none; font-size: 16px; font-weight: bold; border-radius: 4px; }}\n'
        f'QPushButton#toastCloseBtn:hover {{ background: {C.BG_HOVER}; color: {C.TEXT_PRIMARY}; }}\n'
        # ── History dialog ──
        f'QFrame#historyHeader {{ background: {C.CARD_BG}; border-radius: 8px; border: none; }}\n'
        f'QFrame#mediaRow {{ background: {C.CARD_BG}; border-radius: 6px; border: none; }}\n'
        f'QFrame#mediaRow:hover {{ background: {C.BG_HOVER}; }}\n'
        f'QLabel#mediaThumb {{ background: {C.DIALOG_BG}; border-radius: 4px; }}\n'
        f'QLabel#mediaLabel {{ color: {C.TEXT_PRIMARY}; background: transparent; }}\n'
        f'QLabel#mediaMeta {{ color: {C.TEXT_PRIMARY}; font-size: 10px; background: transparent; }}\n'
        f'QLabel#typeBadge {{ color: {C.TEXT_PRIMARY}; border-radius: 3px; padding: 1px 5px; font-size: 9px; background: {C.BG_HOVER}; border: 1px solid {C.BORDER}; }}\n'
        f'QLabel#typeBadge[ct="short"] {{ background: {C.ACCENT_BLUE}; border: 1px solid {C.ACCENT_BLUE_BORDER}; }}\n'
        f'QLabel#typeBadge[ct="stream"] {{ background: {C.DANGER}; border: 1px solid {C.DANGER_RED_BORDER}; }}\n'
        f'QLabel#typeBadge[ct="video"] {{ background: {C.BG_HOVER}; border: 1px solid {C.BORDER}; }}\n'
        f'QPushButton#verifyBtn {{ border: none; border-radius: 4px; font-size: 11px; }}\n'
        f'QPushButton#verifyBtn[verified="true"] {{ background: {C.VERIFY_GREEN}; color: {C.TEXT_ON_ACCENT}; }}\n'
        f'QPushButton#verifyBtn[verified="true"]:hover {{ background: {C.VERIFY_GREEN_HOVER}; }}\n'
        f'QPushButton#verifyBtn[verified="false"] {{ background: {C.BG_PRESS}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.TEXT_MUTED}; }}\n'
        f'QPushButton#verifyBtn[verified="false"]:hover {{ background: {C.BG_HOVER}; }}\n'
        f'QPushButton#chartToggle {{ background: {C.BG_PRESS}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; border-radius: 4px; padding: 4px 12px; }}\n'
        f'QPushButton#chartToggle:checked {{ background: {C.ACCENT}; border-color: {C.ACCENT}; color: {C.TEXT_ON_ACCENT}; }}\n'
        f'QPushButton#chartToggle:hover {{ background: {C.BORDER}; }}\n'
        f'QPushButton#chartToggle:checked:hover {{ background: {C.ACCENT_HOVER}; }}\n'
        f'QPushButton#loadMoreBtn {{ background: {C.BG_HOVER}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; border-radius: 4px; padding: 8px 20px; }}\n'
        f'QPushButton#loadMoreBtn:hover {{ background: {C.BORDER}; }}\n'
        f'QPushButton#refreshContentBtn {{ background-color: {C.ACCENT_BLUE_BG}; color: {C.ACCENT_HOVER}; border: 1px solid {C.ACCENT_BLUE_BORDER}; border-radius: 4px; padding: 6px 12px; }}\n'
        f'QPushButton#refreshContentBtn:hover {{ background-color: {C.ACCENT_BLUE_BORDER}; color: {C.ACCENT_HOVER}; }}\n'
        f'QPushButton#deleteMemberBtn {{ background-color: {C.DANGER_RED_BG}; color: {C.DANGER}; border: 1px solid {C.DANGER_RED_BORDER}; border-radius: 4px; padding: 6px 12px; }}\n'
        f'QPushButton#deleteMemberBtn:hover {{ background-color: {C.DANGER_RED_BORDER}; color: {C.TEXT_PRIMARY}; }}\n'
        f'QPushButton#exportCreatorBtn {{ background-color: {C.BG_PRESS}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; border-radius: 4px; padding: 6px 12px; }}\n'
        f'QPushButton#exportCreatorBtn:hover {{ background-color: {C.BG_HOVER}; }}\n'
        f'QPushButton#verifyCreatorBtn {{ background-color: {C.VERIFY_GREEN}; color: {C.TEXT_ON_ACCENT}; border: 1px solid {C.VERIFY_GREEN}; border-radius: 4px; padding: 6px 12px; }}\n'
        f'QPushButton#verifyCreatorBtn:hover {{ background-color: {C.VERIFY_GREEN_HOVER}; border: 1px solid {C.VERIFY_GREEN_HOVER}; }}\n'
        f'QPushButton#verifyCreatorBtn:disabled {{ background-color: {C.BG_PRESS}; color: {C.TEXT_MUTED}; border: 1px solid {C.BORDER}; }}\n'
        f'QWidget#historyList {{ background: {C.BG_LAYER}; }}\n'
        f'QWidget#historyViewport {{ background: {C.BG_LAYER}; }}\n'
        f'QLabel#historyCount {{ font-size: 11px; background: transparent; color: {C.TEXT_MUTED}; }}\n'
        f'QLabel#historyCount[state="done"] {{ color: {C.INPUT_PLACEHOLDER}; }}\n'
        f'QTextEdit#notesEdit {{ background: {C.BG_LAYER}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; border-radius: 4px; padding: 4px; font-size: 12px; }}\n'
        # ── Verify-dialog card buttons (formerly frozen module-level QSS) ──
        f'QPushButton#verifyCard {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 2px solid {C.BORDER}; border-radius: 8px; padding: 24px 16px; min-height: 100px; font-size: 15px; }}\n'
        f'QPushButton#verifyCard:hover {{ background: {C.BG_HOVER}; border-color: {C.ACCENT}; }}\n'
        f'QPushButton#verifyCard:pressed {{ background: {C.BG_PRESS}; }}\n'
        f'QPushButton#verifyModelCard {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 2px solid {C.BORDER}; border-radius: 6px; padding: 14px 16px; min-height: 48px; font-size: 14px; }}\n'
        f'QPushButton#verifyModelCard:hover {{ background: {C.BG_HOVER}; border-color: {C.ACCENT}; }}\n'
        f'QPushButton#verifyModelCard:pressed {{ background: {C.BG_PRESS}; }}\n'
        f'QPushButton#verifyAccentBtn {{ background: {C.ACCENT}; color: {C.TEXT_ON_ACCENT}; border: none; border-radius: 4px; padding: 8px 20px; font-weight: bold; }}\n'
        f'QPushButton#verifyAccentBtn:hover {{ background: {C.ACCENT_HOVER}; }}\n'
        f'QPushButton#verifyAccentBtn:pressed {{ background: {C.ACCENT_PRESS}; }}\n'
        f'QPushButton#verifyAccentBtn:disabled {{ background: {C.BG_PRESS}; color: {C.TEXT_MUTED}; }}\n'
        f'QPushButton#verifyNavBtn {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; border-radius: 4px; padding: 6px 14px; }}\n'
        f'QPushButton#verifyNavBtn:hover {{ background: {C.BG_HOVER}; }}\n'
    )


def build_dialog_qss() -> str:
    """Return a QSS string for QDialog subclasses using design tokens.

    This provides a complete, consistent theme for all dialog windows.
    Call once in each dialog's __init__ and apply via setStyleSheet().
    For dialog-specific styling, define a ``reapply_theme(self)`` method
    that rebuilds the sheet from tokens; :func:`refresh_all_styles` will
    call it on theme switches instead of clobbering it with this generic
    sheet.
    """
    return (
        f'QDialog {{ background: {C.DIALOG_BG}; }}\n'
        f'QLabel {{ color: {C.TEXT_PRIMARY}; background: transparent; }}\n'
        f'QLineEdit {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.INPUT_BORDER}; border-radius: {M.RADIUS_MD}px; padding: {M.SPACE_XS}px {M.SPACE_MD}px; }}\n'
        f'QLineEdit:focus {{ border-color: {C.ACCENT}; }}\n'
        f'QTextEdit {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.INPUT_BORDER}; border-radius: {M.RADIUS_MD}px; padding: {M.SPACE_XS}px {M.SPACE_MD}px; }}\n'
        f'QTextEdit:focus {{ border-color: {C.ACCENT}; }}\n'
        f'QComboBox {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.INPUT_BORDER}; border-radius: {M.RADIUS_MD}px; padding: {M.SPACE_XS}px {M.SPACE_MD}px; }}\n'
        f'QComboBox::drop-down {{ border: none; }}\n'
        f'QComboBox QAbstractItemView {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; selection-background-color: {C.BG_HOVER}; }}\n'
        f'QPushButton {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; border-radius: {M.RADIUS_MD}px; padding: {M.SPACE_SM}px {M.SPACE_LG}px; }}\n'
        f'QPushButton:hover {{ background: {C.BG_HOVER}; }}\n'
        f'QPushButton:pressed {{ background: {C.BG_PRESS}; }}\n'
        f'QPushButton:checked {{ background: {C.ACCENT}; border-color: {C.ACCENT}; color: {C.TEXT_ON_ACCENT}; }}\n'
        f'QScrollArea {{ border: none; background: transparent; }}\n'
        f'QScrollArea > QWidget {{ background: transparent; }}\n'
        f'QScrollBar:vertical {{ background: {C.BG_LAYER}; width: 8px; border-radius: {M.RADIUS_MD}px; }}\n'
        f'QScrollBar::handle:vertical {{ background: {C.BG_HOVER}; border-radius: {M.RADIUS_MD}px; min-height: 20px; }}\n'
        f'QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}\n'
        f'QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}\n'
        f'QFrame {{ border: none; }}\n'
        f'QMenu {{ background-color: {C.BG_RAISED}; border: 1px solid {C.BORDER}; }}\n'
        f'QMenu::item {{ color: {C.TEXT_PRIMARY}; padding: {M.SPACE_SM}px {M.SPACE_XL}px; }}\n'
        f'QMenu::item:selected {{ background-color: {C.BG_HOVER}; }}\n'
        f'QMenu::separator {{ height: 1px; background: {C.BORDER}; margin: {M.SPACE_XS}px 10px; }}\n'
        f'QTabWidget::pane {{ border: 1px solid {C.BORDER}; background: {C.DIALOG_BG}; }}\n'
        f'QTabBar::tab {{ background: {C.BG_RAISED}; color: {C.TEXT_SECONDARY}; padding: {M.SPACE_SM}px 16px; border: 1px solid {C.BORDER}; border-bottom: none; border-radius: {M.RADIUS_MD}px {M.RADIUS_MD}px 0 0; margin-right: 2px; }}\n'
        f'QTabBar::tab:selected {{ background: {C.DIALOG_BG}; color: {C.TEXT_PRIMARY}; border-bottom: 2px solid {C.ACCENT}; }}\n'
        f'QCheckBox {{ color: {C.TEXT_PRIMARY}; spacing: {M.SPACE_SM}px; }}\n'
        f'QCheckBox::indicator {{ width: 16px; height: 16px; background: {C.INPUT_BG}; border: 1px solid {C.INPUT_BORDER}; border-radius: {M.RADIUS_SM}px; }}\n'
        f'QCheckBox::indicator:checked {{ background: {C.ACCENT}; border: 1px solid {C.ACCENT}; }}\n'
        f'QProgressBar {{ background: {C.BG_RAISED}; border: 1px solid {C.BORDER}; border-radius: {M.RADIUS_MD}px; text-align: center; color: {C.TEXT_PRIMARY}; }}\n'
        f'QProgressBar::chunk {{ background: {C.ACCENT}; border-radius: {M.RADIUS_SM}px; }}\n'
        f'QListWidget {{ background: {C.BG_LAYER}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; border-radius: {M.RADIUS_MD}px; }}\n'
        f'QListWidget::item:selected {{ background: {C.BG_HOVER}; }}\n'
        f'QListWidget::item:hover {{ background: {C.BG_HOVER}; }}\n'
        f'QSpinBox {{ background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.INPUT_BORDER}; border-radius: {M.RADIUS_MD}px; padding: {M.SPACE_XS}px {M.SPACE_MD}px; }}\n'
        f'QDialogButtonBox QPushButton {{ min-width: 80px; }}\n'
        f'QToolTip {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; border: 1px solid {C.BORDER}; padding: {M.SPACE_XS}px {M.SPACE_MD}px; border-radius: {M.RADIUS_MD}px; }}\n'
    )


def build_main_window_qss() -> str:
    """Return the MainWindow-specific stylesheet (object-name keyed).

    Supplements the global stylesheet applied in ``main.py``. Only
    MainWindow-owned selectors are set here; common widget styles are
    inherited from the application stylesheet.
    """
    return (
        f'QMainWindow {{ background: {C.BG_BASE}; }}\n'
        f'QCheckBox::indicator:checked {{ image: none; }}\n'
        f'QWidget#topBar {{ background: {C.TOPBAR_BG}; }}\n'
        f'QWidget#separator {{ background: {C.BORDER}; }}\n'
        f'QLabel#fetchStatus {{ color: {C.TEXT_SECONDARY}; font-size: 11px; background: transparent; }}\n'
        f'QLabel#verifyProgress {{ color: {C.TEXT_SECONDARY}; background: transparent; }}\n'
        f'QLabel#emptyStateIcon {{ font-size: 48px; background: transparent; }}\n'
        f'QLabel#emptyTitle {{ font-size: 18px; font-weight: bold; color: {C.TEXT_PRIMARY}; background: transparent; }}\n'
        f'QLabel#emptyDesc {{ font-size: 13px; color: {C.TEXT_SECONDARY}; background: transparent; }}\n'
        f'QPushButton#emptyBtn {{ background: {C.ACCENT}; color: {C.TEXT_ON_ACCENT}; border: none; border-radius: {M.RADIUS_LG}px; padding: 10px {M.SPACE_XL}px; font-size: 14px; font-weight: bold; }}\n'
        f'QPushButton#emptyBtn:hover {{ background: {C.ACCENT_HOVER}; }}\n'
        # Focus ring for CreatorCard is driven by a dynamic ``focused`` property
        # (toggled in focusInEvent/focusOutEvent + qss_refresh) instead of
        # rebuilding the per-card stylesheet on every focus change.  The
        # per-card stylesheet sets border-left (role colour); this selector
        # sets the other three sides when focused.
        f'CreatorCard[focused="true"] {{ border: 2px solid {C.ACCENT}; }}\n'
    )


def qss_refresh(widget: QWidget) -> None:
    """Force Qt to re-evaluate property/attribute-based QSS selectors.

    Qt caches style computation; after changing a dynamic property (e.g.
    ``setProperty('verified', 'true')``) the widget's appearance is not
    updated until it is unpolished and re-polished.
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def elevation_effect(level: int = 1) -> QGraphicsDropShadowEffect:
    """Build a ``QGraphicsDropShadowEffect`` for the given elevation level.

    Qt QSS has no ``box-shadow`` support, so elevation is applied via
    graphics effects. ``level`` is 1 (resting), 2 (raised), or 3 (floating).
    """
    levels = {1: M.ELEVATION_1, 2: M.ELEVATION_2, 3: M.ELEVATION_3}
    blur, y, alpha = levels.get(level, M.ELEVATION_1)
    r, g, b = M.SHADOW_RGB
    effect = QGraphicsDropShadowEffect()
    effect.setBlurRadius(blur)
    effect.setOffset(0, y)
    effect.setColor(QColor(r, g, b, alpha))
    return effect


def refresh_all_styles() -> None:
    """Re-apply global, main-window, and dialog stylesheets after a theme change.

    Call this after ``theme_manager.apply()`` to push the new colour tokens
    into every open widget. Unlike the previous implementation (which only
    re-skinned open ``QDialog`` top-levels with the generic dialog sheet and
    clobbered dialog-specific styling), this:

    - re-applies the global stylesheet (covers the ``QMainWindow`` and all
      object-name-keyed surfaces via dynamic QSS matching);
    - re-applies the main window's own sheet via ``apply_main_window_qss``;
    - for each open ``QDialog``, calls its ``reapply_theme()`` method if it
      defines one (so dialog-specific styling is preserved), otherwise falls
      back to the generic ``build_dialog_qss()``.
    """
    app = QApplication.instance()
    if app:
        app.setStyleSheet(build_global_qss())
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, QDialog):
            reapply = getattr(widget, 'reapply_theme', None)
            if callable(reapply):
                reapply()
            else:
                widget.setStyleSheet(build_dialog_qss())
        elif hasattr(widget, 'apply_main_window_qss'):
            widget.apply_main_window_qss()