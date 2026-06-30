"""Card-based wizard dialog for selecting a verification method.

Presents the user with a step-by-step flow:
  1. Method selection (Keyword Verify or AI Verify)
  2a. Keyword page — editable keywords field + Start button
  2b. Provider selection (Gemini or Claude)
  3. Model selection — pick a model, which starts AI verification

Uses ``QStackedWidget`` for page transitions.  The caller reads
``result``, ``selected_model``, and ``keywords`` after ``exec()``
returns.
"""
from __future__ import annotations

from enum import IntEnum

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.db_manager import DatabaseManager
from ui.dialog_utils import dark_warning, enable_window_maximize
from ui.geometry import restore_geometry, save_geometry
from ui.theme import C
from ui.theme.stylesheet import build_dialog_qss


class VerifyResult(IntEnum):
    """Result codes returned by :class:`VerifyDialog`."""
    CANCEL = 0
    KEYWORD = 1
    AI = 2


# ── Provider / model definitions ──────────────────────────────────────

_PROVIDERS = {
    'gemini': {
        'label': 'Gemini',
        'icon': '🔮',
        'subtitle': 'Free tier available',
        'models': [
            ('gemini-2.5-flash', '2.5 Flash', 'Fast'),
            ('gemini-2.5-pro', '2.5 Pro', 'Balanced'),
            ('gemini-2.5-flash-lite', '2.5 Flash Lite', 'Lightweight'),
            ('gemini-3.5-flash', '3.5 Flash', 'Latest'),
        ],
    },
    'claude': {
        'label': 'Claude',
        'icon': '🤖',
        'subtitle': 'Anthropic',
        'models': [
            ('claude-haiku-4-5-20251001', 'Haiku 4.5', 'Fastest'),
            ('claude-sonnet-4-6', 'Sonnet 4.6', 'Balanced'),
            ('claude-opus-4-8', 'Opus 4.8', 'Most thorough'),
        ],
    },
}

# ── Card button styles ────────────────────────────────────────────────
# These were previously frozen module-level f-strings that captured the
# import-time theme tokens and never re-evaluated on a theme switch.
# They now live as object-name rules in build_global_qss() so they follow
# theme changes live. Set the matching objectName on each button below.


class VerifyDialog(QDialog):
    """Card-based wizard for choosing a verification method.

    After ``exec()`` returns, read the following attributes to
    determine the user's choice:

    * ``result``       — :class:`VerifyResult` (CANCEL, KEYWORD, or AI)
    * ``selected_model`` — model ID string (when result is AI)
    * ``keywords``     — comma-separated keyword string (when result is KEYWORD)
    """

    def __init__(self, db: DatabaseManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._db = db

        # Result attributes — read by the caller after exec().
        self.result: VerifyResult = VerifyResult.CANCEL
        self.selected_model: str = ''
        self.keywords: str = ''

        self._selected_provider: str = ''

        self.setWindowTitle('Verify')
        self.setMinimumWidth(500)
        self.setMinimumHeight(380)
        enable_window_maximize(self)
        self.reapply_theme()
        restore_geometry(self, 'VerifyDialog', self._db)
        self.finished.connect(lambda _r: save_geometry(self, 'VerifyDialog', self._db))

        # ── Root layout ────────────────────────────────────────────
        root = QVBoxLayout(self)
        root.setSpacing(12)

        # Title
        title = QLabel('Choose Verification Method')
        title.setObjectName('dialogTitle')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label = title
        root.addWidget(title)

        # Stacked pages
        self._stack = QStackedWidget()
        self._method_page = self._build_method_page()
        self._keyword_page = self._build_keyword_page()
        self._provider_page = self._build_provider_page()
        self._model_page = self._build_model_page()
        self._stack.addWidget(self._method_page)    # 0
        self._stack.addWidget(self._keyword_page)    # 1
        self._stack.addWidget(self._provider_page)   # 2
        self._stack.addWidget(self._model_page)      # 3
        root.addWidget(self._stack, 1)

        # ── Navigation bar ─────────────────────────────────────────
        nav = QHBoxLayout()
        nav.setSpacing(8)
        self._back_btn = QPushButton('← Back')
        self._back_btn.setObjectName('verifyNavBtn')
        self._back_btn.clicked.connect(self._on_back)
        nav.addWidget(self._back_btn)
        nav.addStretch(1)
        cancel_btn = QPushButton('Cancel')
        cancel_btn.setObjectName('verifyNavBtn')
        cancel_btn.clicked.connect(self.reject)
        nav.addWidget(cancel_btn)
        root.addLayout(nav)

        self._update_nav_buttons()

    def reapply_theme(self) -> None:
        """Rebuild the dialog stylesheet from current theme tokens."""
        self.setStyleSheet(
            build_dialog_qss()
            + f'QLineEdit::placeholder {{ color: {C.INPUT_PLACEHOLDER}; }}\n'
        )

    # ── Page builders ──────────────────────────────────────────────

    def _build_method_page(self) -> QWidget:
        """Page 0: choose between Keyword and AI verification."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)

        cards = QHBoxLayout()
        cards.setSpacing(12)

        kw_btn = QPushButton('🔑\nKeyword Verify\n\nMatch videos by keywords\n(no AI needed)')
        kw_btn.setObjectName('verifyCard')
        kw_btn.clicked.connect(self._on_method_keyword)
        cards.addWidget(kw_btn)

        ai_btn = QPushButton('🤖\nAI Verify\n\nClassify videos using\nAI models')
        ai_btn.setObjectName('verifyCard')
        ai_btn.clicked.connect(self._on_method_ai)
        cards.addWidget(ai_btn)

        layout.addLayout(cards)
        layout.addStretch(1)
        return page

    def _build_keyword_page(self) -> QWidget:
        """Page 1: keyword verification config."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        kw_label = QLabel('Verification Keywords:')
        kw_label.setObjectName('formLabel')
        layout.addWidget(kw_label)

        self._keywords_edit = QLineEdit()
        saved = self._db.get_setting('verify_keywords') or ''
        self._keywords_edit.setText(saved)
        self._keywords_edit.setPlaceholderText('e.g. arch.mc, ArchMC, ArchMC Network, mc.arch.lol')
        layout.addWidget(self._keywords_edit)

        hint = QLabel(
            'Keywords match as case-insensitive whole words in video titles '
            'and descriptions. Separate multiple keywords with commas.'
        )
        hint.setObjectName('hintLabel')
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addSpacing(8)
        unverified = self._db.get_unverified_media()
        count = len(unverified)
        if count == 0:
            count_text = 'No unverified videos to check.'
        else:
            count_text = f'{count} unverified video{"s" if count != 1 else ""} will be checked.'
        self._kw_count_label = QLabel(count_text)
        self._kw_count_label.setObjectName('countLabel')
        layout.addWidget(self._kw_count_label)

        layout.addStretch(1)

        start_btn = QPushButton('Start Verification')
        start_btn.setObjectName('verifyAccentBtn')
        start_btn.clicked.connect(self._on_start_keyword)
        layout.addWidget(start_btn, alignment=Qt.AlignmentFlag.AlignRight)

        return page

    def _build_provider_page(self) -> QWidget:
        """Page 2: choose between Gemini and Claude."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)

        cards = QHBoxLayout()
        cards.setSpacing(12)

        for key, info in _PROVIDERS.items():
            btn = QPushButton(f'{info["icon"]}\n{info["label"]}\n\n{info["subtitle"]}')
            btn.setObjectName('verifyCard')
            btn.clicked.connect(lambda checked, k=key: self._on_provider_selected(k))
            cards.addWidget(btn)

        layout.addLayout(cards)
        layout.addStretch(1)
        return page

    def _build_model_page(self) -> QWidget:
        """Page 3: model selection — populated dynamically."""
        page = QWidget()
        self._model_layout = QVBoxLayout(page)
        self._model_layout.setSpacing(10)
        self._model_layout.addStretch(1)
        return page

    # ── Dynamic model population ───────────────────────────────────

    def _populate_model_page(self, provider_key: str) -> None:
        """Fill the model page with cards for the selected provider."""
        # Clear existing cards (keep the stretch at the end).
        while self._model_layout.count() > 1:
            item = self._model_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        info = _PROVIDERS[provider_key]
        provider_label = info['label']

        # Insert cards before the stretch.
        for model_id, model_name, speed in info['models']:
            btn = QPushButton(f'{model_name}  —  {speed}')
            btn.setObjectName('verifyModelCard')
            btn.clicked.connect(lambda checked, mid=model_id: self._on_model_selected(mid))
            self._model_layout.insertWidget(self._model_layout.count() - 1, btn)

    # ── Navigation ──────────────────────────────────────────────────

    def _on_method_keyword(self) -> None:
        self._stack.setCurrentIndex(1)
        self._title_label.setText('Keyword Verification')
        self._update_nav_buttons()

    def _on_method_ai(self) -> None:
        self._stack.setCurrentIndex(2)
        self._title_label.setText('Choose AI Provider')
        self._update_nav_buttons()

    def _on_provider_selected(self, provider_key: str) -> None:
        self._selected_provider = provider_key
        self._populate_model_page(provider_key)
        label = _PROVIDERS[provider_key]['label']
        self._title_label.setText(f'Choose {label} Model')
        self._stack.setCurrentIndex(3)
        self._update_nav_buttons()

    def _on_model_selected(self, model_id: str) -> None:
        self.result = VerifyResult.AI
        self.selected_model = model_id
        self.accept()

    def _on_start_keyword(self) -> None:
        kw = self._keywords_edit.text().strip()
        if not kw:
            dark_warning(self, 'No Keywords Set',
                         'Please enter at least one keyword, or go back and choose AI verification.')
            return
        self.result = VerifyResult.KEYWORD
        self.keywords = kw
        self.accept()

    def _on_back(self) -> None:
        idx = self._stack.currentIndex()
        if idx == 1:  # keyword → method
            self._stack.setCurrentIndex(0)
            self._title_label.setText('Choose Verification Method')
        elif idx == 2:  # provider → method
            self._stack.setCurrentIndex(0)
            self._title_label.setText('Choose Verification Method')
        elif idx == 3:  # model → provider
            self._stack.setCurrentIndex(2)
            self._title_label.setText('Choose AI Provider')
        self._update_nav_buttons()

    def _update_nav_buttons(self) -> None:
        idx = self._stack.currentIndex()
        self._back_btn.setVisible(idx > 0)

    def reject(self) -> None:
        self.result = VerifyResult.CANCEL
        super().reject()