"""Ctrl+K command palette — a fuzzy-searchable launcher for app actions.

Opens as a frameless modal dialog with a search field and a result list.  The
caller builds a list of :class:`Action` objects referencing existing entry
points (no new logic lives here) and passes it to :class:`CommandPalette`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout,
)

from ui.theme.stylesheet import build_dialog_qss


@dataclass
class Action:
    """A single palette entry.

    ``label`` is what the user sees and what the fuzzy matcher scores against
    first; ``keywords`` carries extra matchable terms (e.g. shortcuts).  The
    ``trigger`` callable is invoked when the entry is activated.
    """
    id: str
    label: str
    trigger: Callable[[], None] = field(default=lambda: None)
    hint: str = ''
    keywords: str = ''


def _fuzzy_score(query: str, action: Action) -> int | None:
    """Return a match score (higher = better) or ``None`` for no match.

    A subsequence match of ``query`` against the label+keywords haystack is
    required; consecutive matches and matches at word boundaries score higher
    so intuitively-spelled queries rank above accidental ones.
    """
    hay = f'{action.label} {action.keywords}'.lower()
    if not query:
        return 0
    idx = 0
    score = 0
    prev_was_boundary = True
    for ch in query:
        pos = hay.find(ch, idx)
        if pos < 0:
            return None
        if pos == idx:
            score += 5  # consecutive continuation
        else:
            score += 1
        if prev_was_boundary or (pos > 0 and hay[pos - 1] in ' ._-/'):
            score += 4  # matched the start of a word
        prev_was_boundary = (pos + 1 < len(hay) and hay[pos + 1] in ' ._-/')
        idx = pos + 1
    return score


class _PaletteEdit(QLineEdit):
    """Search field that forwards navigation keys to the result list."""

    def __init__(self, palette: 'CommandPalette') -> None:
        super().__init__()
        self._palette = palette

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Down:
            self._palette._move_selection(1)
            return
        if key == Qt.Key.Key_Up:
            self._palette._move_selection(-1)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._palette._activate_current()
            return
        if key == Qt.Key.Key_Escape:
            self._palette.reject()
            return
        super().keyPressEvent(event)


class CommandPalette(QDialog):
    """Modal palette dialog: type to filter, arrow keys to move, Enter to run."""

    def __init__(self, actions: list[Action], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName('commandPalette')
        self.setWindowTitle('Command Palette')
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setMinimumWidth(440)
        self.resize(500, 340)
        self.setStyleSheet(build_dialog_qss())

        self._actions = list(actions)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._edit = _PaletteEdit(self)
        self._edit.setPlaceholderText('Search commands…  (↑↓ to move, Enter to run, Esc to close)')
        self._edit.textChanged.connect(self._refilter)
        layout.addWidget(self._edit)

        self._list = QListWidget()
        self._list.setUniformItemSizes(True)
        self._list.itemActivated.connect(self._activate_item)
        layout.addWidget(self._list, 1)

        self._refilter('')

    # -- filtering ----------------------------------------------------------

    def _refilter(self, text: str) -> None:
        query = text.strip().lower()
        scored: list[tuple[int, Action]] = []
        for a in self._actions:
            s = _fuzzy_score(query, a)
            if s is not None:
                scored.append((s, a))
        # Stable order: by score desc, then original order.
        scored.sort(key=lambda sa: (-sa[0], self._actions.index(sa[1])))
        self._list.clear()
        for _score, a in scored[:10]:
            label = a.label
            if a.hint:
                label = f'{label}   ·   {a.hint}'
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, a)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)

    # -- selection / activation --------------------------------------------

    def _move_selection(self, delta: int) -> None:
        n = self._list.count()
        if n == 0:
            return
        row = self._list.currentRow() + delta
        row = max(0, min(n - 1, row))
        self._list.setCurrentRow(row)

    def _activate_current(self) -> None:
        item = self._list.currentItem()
        if item is not None:
            self._activate_item(item)

    def _activate_item(self, item: QListWidgetItem) -> None:
        action: Action | None = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        if action is not None:
            action.trigger()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._edit.setFocus()
        self._edit.selectAll()