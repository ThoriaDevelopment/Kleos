import os
import sys
import logging
# Set tooltip display duration to 3 seconds (must be set before QApplication init)
os.environ['QT_TOOLTIP_TIMEOUT'] = '3000'
from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QProxyStyle, QStackedWidget, QStyle, QStyleOption, QToolTip, QVBoxLayout, QWidget
from core.db_manager import DatabaseManager, determine_startup_profile
from core.paths import APP_DIR, BACKUPS_DIR, STORAGE_DIR, THUMBNAILS_DIR
from ui.app_icon import create_app_icon
from ui.main_window import MainWindow
from ui.theme import build_global_qss
from ui.theme.tokens import C, theme_manager


class _KleosStyle(QProxyStyle):
    """Custom proxy style that slows down tooltip behaviour.

    - WakeUpDelay: 700 ms hover before a tooltip appears.
    - FallAsleepDelay: 250 ms gap after a tooltip hides before the next
      one can appear.  This prevents the "instant re-show" problem where
      moving from one button to the next immediately shows the new tooltip
      without any hover delay.
    """

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
            return 700
        if hint == QStyle.StyleHint.SH_ToolTip_FallAsleepDelay:
            return 250
        return super().styleHint(hint, option, widget, returnData)


def _enable_dwm_dark_title_bar(window) -> None:
    """Force the Windows native title bar to dark mode via DWM API."""
    if sys.platform != 'win32':
        return None
    else:
        import ctypes
        hwnd = int(window.winId())
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value))


logger = logging.getLogger(__name__)


def initialize_app_data() -> bool:
    """Ensure the %APPDATA%\\.kleos directory tree exists.

    Returns True on success, False on failure.
    """
    for d in [APP_DIR, STORAGE_DIR, BACKUPS_DIR, THUMBNAILS_DIR]:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error('Failed to create directory %s: %s', d, exc)
            return False
    return True


class FirstRunWizard(QDialog):
    """Multi-step welcome dialog shown on the first launch of Kleos.

    Pages: Welcome → API Keys → 8 feature walkthroughs → Done.
    Each feature page shows a heading, description, and a visual mockup
    of the relevant part of the UI.
    """

    _NUM_PAGES = 10

    # ── Shared stylesheet ──────────────────────────────────────────────
    _STYLE = (
        f'QDialog {{ background: {C.BG_BASE}; }}'
        f'QLabel {{ color: {C.TEXT_PRIMARY}; background: transparent; }}'
        f'QPushButton {{ background: {C.BG_RAISED}; color: {C.TEXT_PRIMARY}; '
        f'border: 1px solid {C.BORDER}; border-radius: 4px; padding: 8px 16px; }}'
        f'QPushButton:hover {{ background: {C.BG_HOVER}; }}'
        f'QPushButton:disabled {{ color: {C.TEXT_MUTED}; background: {C.BG_LAYER}; }}'
    )
    _ACCENT_BTN = (
        f'QPushButton {{ background-color: {C.CHECK_ACCENT}; color: {C.TEXT_ON_ACCENT}; '
        f'border: 1px solid {C.ACCENT_BLUE_BORDER}; border-radius: 4px; padding: 8px 20px; }}'
        f'QPushButton:hover {{ background-color: {C.ACCENT_BLUE_BORDER}; color: {C.ACCENT_HOVER}; }}'
    )

    # ── Mockup helpers ──────────────────────────────────────────────────

    @staticmethod
    def _mock_frame() -> QFrame:
        """Dark raised frame used as the outer container for mockups."""
        f = QFrame()
        f.setStyleSheet(
            f'QFrame {{ background: {C.BG_RAISED}; border: 1px solid {C.BORDER}; '
            f'border-radius: 8px; }}'
            f'QLabel {{ background: transparent; }}'
        )
        return f

    @staticmethod
    def _mock_card(nickname: str = 'CreatorName', role: str = 'Member',
                   platform: str = 'Creator', subs: str = '12.5K subs') -> QFrame:
        """Mini creator-card mockup with role stripe, avatar placeholder, and info."""
        card = QFrame()
        card.setStyleSheet(
            f'QFrame {{ background: {C.BG_RAISED}; border: 1px solid {C.BORDER}; '
            f'border-radius: 6px; }}'
            f'QLabel {{ background: transparent; }}'
        )
        h = QHBoxLayout(card)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)

        # Role color stripe
        stripe = QFrame()
        stripe.setFixedWidth(4)
        stripe.setStyleSheet(f'background: {C.ACCENT}; border-radius: 2px;')
        h.addWidget(stripe)

        # Avatar placeholder
        avatar = QLabel('👤')
        avatar_font = QFont()
        avatar_font.setPointSize(18)
        avatar.setFont(avatar_font)
        avatar.setFixedSize(36, 36)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            f'background: {C.AVATAR_BG}; border-radius: 4px; color: {C.AVATAR_FG};'
        )
        h.addWidget(avatar)

        # Text column
        col = QVBoxLayout()
        col.setSpacing(1)
        nick = QLabel(nickname)
        nick_font = QFont()
        nick_font.setBold(True)
        nick.setFont(nick_font)
        col.addWidget(nick)
        detail = QLabel(f'{platform}  ·  {subs}')
        detail.setStyleSheet(f'color: {C.TEXT_SECONDARY}; font-size: 11px;')
        col.addWidget(detail)
        h.addLayout(col, 1)

        return card

    @staticmethod
    def _mock_search_bar() -> QFrame:
        """Mini search bar mockup."""
        bar = QFrame()
        bar.setStyleSheet(
            f'QFrame {{ background: {C.INPUT_BG}; border: 1px solid {C.INPUT_BORDER}; '
            f'border-radius: 4px; }}'
            f'QLabel {{ background: transparent; }}'
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(6)
        icon = QLabel('🔍')
        h.addWidget(icon)
        placeholder = QLabel('Search members…')
        placeholder.setStyleSheet(f'color: {C.INPUT_PLACEHOLDER};')
        h.addWidget(placeholder, 1)
        return bar

    @staticmethod
    def _mock_context_menu() -> QFrame:
        """Mini context-menu dropdown mockup."""
        menu = QFrame()
        menu.setStyleSheet(
            f'QFrame {{ background: {C.BG_FLOAT}; border: 1px solid {C.BORDER}; '
            f'border-radius: 4px; }}'
            f'QLabel {{ background: transparent; padding: 3px 8px; }}'
        )
        v = QVBoxLayout(menu)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(2)
        for item in ['Edit Nickname', 'Edit Platforms', 'Edit Notes', 'Refresh Data',
                      'Delete Member']:
            lbl = QLabel(item)
            if item == 'Delete Member':
                lbl.setStyleSheet(
                    f'color: {C.DANGER}; background: transparent; padding: 3px 8px;'
                )
            v.addWidget(lbl)
        return menu

    @staticmethod
    def _mock_verify_row(title: str = 'Latest Video Title', verified: bool = True) -> QFrame:
        """Mini content row mockup showing a thumbnail + title + verify badge."""
        row = QFrame()
        row.setStyleSheet(
            f'QFrame {{ background: {C.BG_RAISED}; border: 1px solid {C.BORDER}; '
            f'border-radius: 4px; }}'
            f'QLabel {{ background: transparent; }}'
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(10, 8, 10, 8)
        h.setSpacing(10)

        # Thumbnail placeholder
        thumb = QLabel('🖼')
        thumb.setFixedSize(48, 28)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setStyleSheet(
            f'background: {C.BG_LAYER}; border-radius: 3px; color: {C.TEXT_MUTED};'
        )
        h.addWidget(thumb)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f'font-size: 12px;')
        h.addWidget(title_lbl, 1)

        badge_text = '✓ In Community' if verified else 'Verify'
        badge_color = C.VERIFY_GREEN if verified else C.TEXT_MUTED
        badge_bg = C.BG_RAISED if verified else C.BG_LAYER
        badge = QLabel(badge_text)
        badge.setStyleSheet(
            f'background: {badge_bg}; color: {badge_color}; '
            f'border: 1px solid {badge_color}; border-radius: 3px; '
            f'padding: 2px 8px; font-size: 11px;'
        )
        h.addWidget(badge)

        return row

    @staticmethod
    def _mock_chart_bars() -> QFrame:
        """Mini bar chart mockup for leaderboard page."""
        chart = QFrame()
        chart.setStyleSheet(
            f'QFrame {{ background: {C.BG_LAYER}; border: 1px solid {C.BORDER}; '
            f'border-radius: 6px; }}'
            f'QLabel {{ background: transparent; }}'
        )
        h = QHBoxLayout(chart)
        h.setContentsMargins(16, 12, 16, 12)
        h.setSpacing(6)
        heights = [0.4, 0.65, 0.9, 0.55, 0.75, 0.35, 0.6, 0.5]
        for frac in heights:
            bar = QFrame()
            bar.setFixedHeight(int(80 * frac))
            bar.setMinimumWidth(14)
            bar.setStyleSheet(
                f'background: {C.ACCENT}; border-radius: 2px;'
            )
            h.addWidget(bar)
        return chart

    @staticmethod
    def _mock_rank_list() -> QFrame:
        """Mini ranked list mockup."""
        box = QFrame()
        box.setStyleSheet(
            f'QFrame {{ background: {C.BG_RAISED}; border: 1px solid {C.BORDER}; '
            f'border-radius: 6px; }}'
            f'QLabel {{ background: transparent; }}'
        )
        v = QVBoxLayout(box)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(4)
        rankings = [
            ('1.', 'Alice', '1,250,000 views'),
            ('2.', 'Bob', '980,000 views'),
            ('3.', 'Charlie', '740,000 views'),
        ]
        for rank, name, views in rankings:
            row = QLabel(f'{rank}  {name}  —  {views}')
            row.setStyleSheet(f'color: {C.TEXT_PRIMARY}; font-size: 11px; padding: 2px 0;')
            v.addWidget(row)
        return box

    @staticmethod
    def _mock_notes_area() -> QFrame:
        """Mini notes text-area mockup."""
        frame = QFrame()
        frame.setStyleSheet(
            f'QFrame {{ background: {C.BG_RAISED}; border: 1px solid {C.BORDER}; '
            f'border-radius: 6px; }}'
            f'QLabel {{ background: transparent; }}'
        )
        v = QVBoxLayout(frame)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(4)
        lbl = QLabel('📝 Notes')
        lbl_font = QFont()
        lbl_font.setBold(True)
        lbl.setFont(lbl_font)
        v.addWidget(lbl)
        notes = QLabel(
            'Streams every Tuesday and Thursday.\n'
            'Collaborated with Channel X in March.\n'
            'Working on a new series starting June.'
        )
        notes.setStyleSheet(
            f'color: {C.TEXT_SECONDARY}; font-size: 11px; '
            f'background: {C.INPUT_BG}; border-radius: 3px; padding: 6px;'
        )
        v.addWidget(notes)
        return frame

    @staticmethod
    def _mock_shortcut_grid() -> QFrame:
        """Grid of keyboard shortcut badges."""
        frame = QFrame()
        frame.setStyleSheet(
            f'QFrame {{ background: transparent; }}'
            f'QLabel {{ background: transparent; }}'
        )
        grid = QGridLayout(frame)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        shortcuts = [
            ('Ctrl+R', 'Refresh All'),
            ('Ctrl+N', 'Add Member'),
            ('Ctrl+F', 'Focus Search'),
            ('Esc', 'Clear Search'),
            ('F11', 'Fullscreen'),
        ]
        for i, (key, desc) in enumerate(shortcuts):
            key_lbl = QLabel(key)
            key_lbl.setStyleSheet(
                f'background: {C.BG_LAYER}; color: {C.ACCENT}; '
                f'border: 1px solid {C.ACCENT}; border-radius: 4px; '
                f'padding: 4px 10px; font-family: monospace; font-size: 12px;'
            )
            key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(key_lbl, i, 0)

            desc_lbl = QLabel(desc)
            desc_lbl.setStyleSheet(f'font-size: 12px; padding-left: 4px;')
            grid.addWidget(desc_lbl, i, 1)

        return frame

    # ── Constructor ─────────────────────────────────────────────────────

    def __init__(self, db: DatabaseManager, parent=None):
        super().__init__(parent)
        self._db = db
        self.setWindowTitle('Welcome to Kleos')
        self.setWindowIcon(create_app_icon())
        self.setMinimumWidth(540)
        self.setMinimumHeight(480)
        self.setStyleSheet(self._STYLE)

        # ── Page stack ─────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._build_page_welcome()
        self._build_page_api_keys()
        self._build_page_add_members()
        self._build_page_view_history()
        self._build_page_context_menu()
        self._build_page_verify()
        self._build_page_leaderboard()
        self._build_page_search_filter()
        self._build_page_notes()
        self._build_page_shortcuts()

        # ── Navigation bar ──────────────────────────────────────────────
        nav = self._build_nav()

        # ── Assemble ────────────────────────────────────────────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._stack, 1)
        outer.addLayout(nav)

        self._update_nav()

    # ── Page builders ───────────────────────────────────────────────────

    def _build_page_welcome(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 40, 32, 24)
        lay.setSpacing(16)

        title = QLabel('Welcome to Kleos!')
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(20)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        desc = QLabel(
            'Kleos helps you track media creators across YouTube and Twitch. '
            'Monitor content, verify uploads, and manage your community — '
            'all from one dashboard.\n\n'
            'This quick setup will walk you through the key features so you '
            'can get the most out of Kleos.'
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(desc)

        lay.addStretch(1)
        self._stack.addWidget(page)

    def _build_page_api_keys(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 40, 32, 24)
        lay.setSpacing(16)

        title = QLabel('API Keys')
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(16)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        desc = QLabel(
            'To fetch data from YouTube and Twitch, Kleos needs API keys.\n\n'
            'You can set them up now, or add them later via ⚙ Settings → API Keys.'
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(desc)

        lay.addSpacing(12)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        settings_btn = QPushButton('Set up API Keys')
        settings_btn.setStyleSheet(self._ACCENT_BTN)
        settings_btn.clicked.connect(self._open_settings)
        btn_row.addWidget(settings_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        lay.addStretch(1)
        self._stack.addWidget(page)

    # ── Feature pages ──────────────────────────────────────────────────

    def _build_page_add_members(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 28, 32, 16)
        lay.setSpacing(12)

        emoji = QLabel('🎬')
        emoji_font = QFont()
        emoji_font.setPointSize(28)
        emoji.setFont(emoji_font)
        emoji.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(emoji)

        title = QLabel('Add Members')
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(16)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        desc = QLabel(
            'Click the + button in the toolbar or press Ctrl+N to add a creator. '
            'Enter their YouTube/Twitch links and assign a role.'
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(f'color: {C.TEXT_SECONDARY};')
        lay.addWidget(desc)

        lay.addSpacing(8)

        # Mockup: toolbar + card
        mock = self._mock_frame()
        mock_lay = QVBoxLayout(mock)
        mock_lay.setContentsMargins(12, 10, 12, 10)
        mock_lay.setSpacing(8)

        # Mini toolbar
        tb = QHBoxLayout()
        add_btn = QLabel('  ＋ Add Member  ')
        add_btn.setStyleSheet(
            f'background: {C.CHECK_ACCENT}; color: {C.ACCENT_HOVER}; '
            f'border-radius: 3px; padding: 4px 10px; font-size: 11px;'
        )
        tb.addWidget(add_btn)
        tb.addStretch(1)
        mock_lay.addLayout(tb)

        # Mini card
        mock_lay.addWidget(self._mock_card())

        lay.addWidget(mock)
        lay.addStretch(1)
        self._stack.addWidget(page)

    def _build_page_view_history(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 28, 32, 16)
        lay.setSpacing(12)

        emoji = QLabel('📊')
        emoji_font = QFont()
        emoji_font.setPointSize(28)
        emoji.setFont(emoji_font)
        emoji.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(emoji)

        title = QLabel('View History')
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(16)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        desc = QLabel(
            'Double-click any creator card to open their full media history '
            'with thumbnails, view counts, and interactive charts.'
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(f'color: {C.TEXT_SECONDARY};')
        lay.addWidget(desc)

        lay.addSpacing(8)

        # Mockup: card with double-click hint → history window
        mock = self._mock_frame()
        mock_lay = QVBoxLayout(mock)
        mock_lay.setContentsMargins(12, 10, 12, 10)
        mock_lay.setSpacing(8)

        card_row = QHBoxLayout()
        card_row.addWidget(self._mock_card('Alice', 'Streamer / Creator', 'Streamer / Creator', '45.2K subs'))
        hint = QLabel('  ×2 click  →')
        hint.setStyleSheet(f'color: {C.ACCENT}; font-size: 12px; font-weight: bold;')
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_row.addWidget(hint)
        mock_lay.addLayout(card_row)

        # Mini history placeholder
        hist = QFrame()
        hist.setStyleSheet(
            f'QFrame {{ background: {C.BG_LAYER}; border: 1px solid {C.BORDER}; '
            f'border-radius: 4px; }}'
            f'QLabel {{ background: transparent; }}'
        )
        hist_lay = QVBoxLayout(hist)
        hist_lay.setContentsMargins(8, 6, 8, 6)
        hist_lay.setSpacing(4)
        for t in ['Latest Video Title', 'Previous Stream Title', 'Older Upload Title']:
            hist_lay.addWidget(self._mock_verify_row(t, verified=True))
        mock_lay.addWidget(hist)

        lay.addWidget(mock)
        lay.addStretch(1)
        self._stack.addWidget(page)

    def _build_page_context_menu(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 28, 32, 16)
        lay.setSpacing(12)

        emoji = QLabel('🖱️')
        emoji_font = QFont()
        emoji_font.setPointSize(28)
        emoji.setFont(emoji_font)
        emoji.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(emoji)

        title = QLabel('Right-Click Menu')
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(16)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        desc = QLabel(
            'Right-click any creator card to edit their nickname, platforms, '
            'date added, notes, or to delete them.'
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(f'color: {C.TEXT_SECONDARY};')
        lay.addWidget(desc)

        lay.addSpacing(8)

        # Mockup: card + context menu overlay
        mock = self._mock_frame()
        mock_lay = QVBoxLayout(mock)
        mock_lay.setContentsMargins(12, 10, 12, 10)
        mock_lay.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(self._mock_card())
        row.addSpacing(6)
        row.addWidget(self._mock_context_menu())
        row.addStretch(1)
        mock_lay.addLayout(row)

        lay.addWidget(mock)
        lay.addStretch(1)
        self._stack.addWidget(page)

    def _build_page_verify(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 28, 32, 16)
        lay.setSpacing(12)

        emoji = QLabel('✅')
        emoji_font = QFont()
        emoji_font.setPointSize(28)
        emoji.setFont(emoji_font)
        emoji.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(emoji)

        title = QLabel('Verify Content')
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(16)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        desc = QLabel(
            'Mark videos as "In Community" to include them in reports and leaderboards. '
            'Use the verify button on each row, or click ✓ Verify on the toolbar to choose '
            'between Keyword Verification (match by keywords, no AI needed) and AI Verification '
            '(let Claude or Gemini check them all).'
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(f'color: {C.TEXT_SECONDARY};')
        lay.addWidget(desc)

        lay.addSpacing(8)

        # Mockup: content rows with verify badges
        mock = self._mock_frame()
        mock_lay = QVBoxLayout(mock)
        mock_lay.setContentsMargins(12, 10, 12, 10)
        mock_lay.setSpacing(6)

        mock_lay.addWidget(self._mock_verify_row('Community Collab Stream', verified=True))
        mock_lay.addWidget(self._mock_verify_row('Random Gaming Video', verified=False))
        mock_lay.addWidget(self._mock_verify_row('Another Upload', verified=True))

        lay.addWidget(mock)
        lay.addStretch(1)
        self._stack.addWidget(page)

    def _build_page_leaderboard(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 28, 32, 16)
        lay.setSpacing(12)

        emoji = QLabel('👑')
        emoji_font = QFont()
        emoji_font.setPointSize(28)
        emoji.setFont(emoji_font)
        emoji.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(emoji)

        title = QLabel('Leaderboard & Analytics')
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(16)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        desc = QLabel(
            'Open the leaderboard to see rankings by views, toggle between '
            'Timeline and Upload Activity charts, and generate shareable reports.'
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(f'color: {C.TEXT_SECONDARY};')
        lay.addWidget(desc)

        lay.addSpacing(8)

        # Mockup: ranked list + chart
        mock = self._mock_frame()
        mock_lay = QHBoxLayout(mock)
        mock_lay.setContentsMargins(12, 10, 12, 10)
        mock_lay.setSpacing(12)
        mock_lay.addWidget(self._mock_rank_list())
        mock_lay.addWidget(self._mock_chart_bars(), 1)

        lay.addWidget(mock)
        lay.addStretch(1)
        self._stack.addWidget(page)

    def _build_page_search_filter(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 28, 32, 16)
        lay.setSpacing(12)

        emoji = QLabel('🔍')
        emoji_font = QFont()
        emoji_font.setPointSize(28)
        emoji.setFont(emoji_font)
        emoji.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(emoji)

        title = QLabel('Search & Filter')
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(16)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        desc = QLabel(
            'Quickly find members by name, sort by subscribers or date, '
            'and filter by role to focus on specific groups.'
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(f'color: {C.TEXT_SECONDARY};')
        lay.addWidget(desc)

        lay.addSpacing(8)

        # Mockup: search bar + filter dropdowns
        mock = self._mock_frame()
        mock_lay = QVBoxLayout(mock)
        mock_lay.setContentsMargins(12, 10, 12, 10)
        mock_lay.setSpacing(8)

        # Search bar
        mock_lay.addWidget(self._mock_search_bar())

        # Filter row
        filter_row = QHBoxLayout()
        for label_text in ['Sort: Subscribers ▾', 'Filter: All Roles ▾']:
            lbl = QLabel(label_text)
            lbl.setStyleSheet(
                f'background: {C.INPUT_BG}; color: {C.TEXT_PRIMARY}; '
                f'border: 1px solid {C.INPUT_BORDER}; border-radius: 3px; padding: 4px 10px; '
                f'font-size: 11px;'
            )
            filter_row.addWidget(lbl)
        filter_row.addStretch(1)
        mock_lay.addLayout(filter_row)

        # Mini cards
        mock_lay.addWidget(self._mock_card('Alice', 'Streamer / Creator', 'Streamer / Creator', '45.2K subs'))
        mock_lay.addWidget(self._mock_card('Bob', 'Member', 'Creator', '12.5K subs'))

        lay.addWidget(mock)
        lay.addStretch(1)
        self._stack.addWidget(page)

    def _build_page_notes(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 28, 32, 16)
        lay.setSpacing(12)

        emoji = QLabel('📝')
        emoji_font = QFont()
        emoji_font.setPointSize(28)
        emoji.setFont(emoji_font)
        emoji.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(emoji)

        title = QLabel('Creator Notes')
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(16)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        desc = QLabel(
            'Add internal notes to any creator — right-click a card and choose '
            '"Edit Notes", or find the notes field in their history window. '
            'Notes are auto-saved and included in exports.'
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(f'color: {C.TEXT_SECONDARY};')
        lay.addWidget(desc)

        lay.addSpacing(8)

        # Mockup: card + notes area
        mock = self._mock_frame()
        mock_lay = QVBoxLayout(mock)
        mock_lay.setContentsMargins(12, 10, 12, 10)
        mock_lay.setSpacing(8)

        mock_lay.addWidget(self._mock_card())
        mock_lay.addWidget(self._mock_notes_area())

        lay.addWidget(mock)
        lay.addStretch(1)
        self._stack.addWidget(page)

    def _build_page_shortcuts(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 28, 32, 16)
        lay.setSpacing(12)

        emoji = QLabel('⌨️')
        emoji_font = QFont()
        emoji_font.setPointSize(28)
        emoji.setFont(emoji_font)
        emoji.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(emoji)

        title = QLabel('Keyboard Shortcuts')
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(16)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        desc = QLabel(
            'Navigate Kleos quickly with these keyboard shortcuts. '
            'You can also hover over any toolbar button to see what it does.'
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(f'color: {C.TEXT_SECONDARY};')
        lay.addWidget(desc)

        lay.addSpacing(12)

        # Shortcut grid mockup
        mock = self._mock_frame()
        mock_lay = QVBoxLayout(mock)
        mock_lay.setContentsMargins(16, 14, 16, 14)
        mock_lay.addWidget(self._mock_shortcut_grid())

        lay.addWidget(mock)
        lay.addStretch(1)
        self._stack.addWidget(page)

    # ── Navigation bar ─────────────────────────────────────────────────

    def _build_nav(self) -> QHBoxLayout:
        nav = QHBoxLayout()
        nav.setContentsMargins(24, 12, 24, 16)
        nav.setSpacing(12)

        self._back_btn = QPushButton('← Back')
        self._back_btn.clicked.connect(self._go_back)
        nav.addWidget(self._back_btn)

        nav.addStretch(1)

        # Step counter label (cleaner than 10 dots)
        self._step_label = QLabel()
        self._step_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._step_label.setStyleSheet(f'color: {C.TEXT_SECONDARY}; font-size: 11px;')
        nav.addWidget(self._step_label)

        nav.addStretch(1)

        self._next_btn = QPushButton('Next →')
        self._next_btn.setStyleSheet(self._ACCENT_BTN)
        self._next_btn.clicked.connect(self._go_next)
        nav.addWidget(self._next_btn)

        return nav

    def _update_nav(self):
        idx = self._stack.currentIndex()
        self._back_btn.setEnabled(idx > 0)

        # Step counter
        self._step_label.setText(f'{idx + 1} / {self._NUM_PAGES}')

        # Last page = "Get Started"
        if idx == self._NUM_PAGES - 1:
            self._next_btn.setText('Get Started')
        else:
            self._next_btn.setText('Next →')

    def _go_back(self):
        idx = self._stack.currentIndex()
        if idx > 0:
            self._stack.setCurrentIndex(idx - 1)
            self._update_nav()

    def _go_next(self):
        idx = self._stack.currentIndex()
        if idx < self._NUM_PAGES - 1:
            self._stack.setCurrentIndex(idx + 1)
            self._update_nav()
        else:
            self.accept()

    def _open_settings(self):
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self._db, self)
        dlg.exec()


class _ToolTipResetFilter(QObject):
    """Application-level event filter that hides the visible tooltip
    whenever the mouse leaves a widget that has one.  This forces Qt
    to restart the wake-up delay for the next tooltip, preventing the
    "instant re-show" problem where moving between buttons skips the
    hover-delay entirely."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Leave and event.spontaneous():
            if isinstance(obj, QWidget) and obj.toolTip():
                QToolTip.hideText()
        return False


def main() -> None:
    if not initialize_app_data():
        app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, 'Startup Error',
            'Kleos could not create its data directory.\n'
            'Please check that you have write access to:\n'
            f'{APP_DIR}')
        sys.exit(1)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle(_KleosStyle(app.style()))
    app.setWindowIcon(create_app_icon())
    db = DatabaseManager(determine_startup_profile())

    # Apply saved theme (must happen before global stylesheet and window)
    saved_theme = db.get_setting('theme') or 'default'
    theme_manager.apply(saved_theme)
    app.setStyleSheet(build_global_qss())

    # First-run wizard: show only once, only mark complete if user accepted
    first_run = db.get_global_setting('first_run_complete')
    if not first_run:
        wizard = FirstRunWizard(db)
        result = wizard.exec()
        if result == QDialog.DialogCode.Accepted:
            db.set_global_setting('first_run_complete', '1')

    window = MainWindow(db)
    _enable_dwm_dark_title_bar(window)
    # Application-level event filter: hide tooltips on Leave so the
    # wake-up delay resets when moving between buttons.
    tip_filter = _ToolTipResetFilter(app)
    app.installEventFilter(tip_filter)
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()