"""Candidate Pool dialog — flagged discovered creators with outreach notes.

Launched from the main dashboard toolbar.  Shows the flagged subset of
discovered creators, each with a freeform notes field (the "status" — the
user just writes whatever one-word or sentence they want), the date flagged,
and a one-click promote-to-roster action.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from core.db_manager import DatabaseManager
from ui.app_icon import create_app_icon
from ui.dialog_utils import dark_info, dark_warning, enable_window_maximize, handle_fullscreen_keypress
from ui.dialog_utils import compact_count as _fmt_count
from ui.geometry import restore_geometry, save_geometry
from ui.theme.stylesheet import build_dialog_qss
from ui.theme.tokens import C, M


class _CandidateRow(QFrame):
    """One flagged candidate: stats + editable notes + actions."""

    def __init__(self, data: dict, dialog: 'CandidatePoolDialog') -> None:
        super().__init__()
        self._data = data
        self._dialog = dialog
        self.setObjectName('card')
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(400)
        self._debounce.timeout.connect(self._save_notes)

        h = QHBoxLayout(self)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(12)

        # Identity + stats.
        info = QVBoxLayout()
        info.setSpacing(2)
        title = QLabel(data.get('title', '(unknown)'))
        title.setObjectName('cardName')
        info.addWidget(title)
        handle = QLabel(data.get('handle') or data.get('channel_id', ''))
        handle.setObjectName('cardSubs')
        info.addWidget(handle)
        stats = QLabel(
            f'{_fmt_count(data.get("subscriber_count", 0))} subs · '
            f'{_fmt_count(data.get("view_count", 0))} views · '
            f'{data.get("views_per_sub", 0):.1f} views/sub · '
            f'Potential {data.get("potential_score", 0)}'
        )
        stats.setObjectName('cardMeta')
        info.addWidget(stats)
        h.addLayout(info, 1)

        # Notes (freeform "status" — the user writes whatever they want).
        notes_box = QVBoxLayout()
        notes_box.setSpacing(2)
        notes_lbl = QLabel('Notes:')
        notes_lbl.setObjectName('countLabel')
        notes_box.addWidget(notes_lbl)
        self._notes_edit = QLineEdit()
        self._notes_edit.setPlaceholderText('e.g. "contacted", "reach out monday", "collab angle…"')
        self._notes_edit.setText(data.get('notes', '') or '')
        self._notes_edit.setMinimumWidth(260)
        self._notes_edit.textChanged.connect(self._on_notes_changed)
        notes_box.addWidget(self._notes_edit)
        h.addLayout(notes_box, 2)

        # Actions.
        add_btn = QPushButton('+ Add to roster')
        add_btn.setToolTip('Promote to the tracked roster')
        add_btn.clicked.connect(self._on_add)
        h.addWidget(add_btn)
        unflag_btn = QPushButton('✕ Unflag')
        unflag_btn.setObjectName('ghost')
        unflag_btn.setToolTip('Remove from the candidate pool (keeps the discovered row)')
        unflag_btn.clicked.connect(self._on_unflag)
        h.addWidget(unflag_btn)

    def _on_notes_changed(self) -> None:
        self._debounce.start()

    def _save_notes(self) -> None:
        self._dialog.save_notes(self._data['channel_id'], self._notes_edit.text())

    def _on_add(self) -> None:
        self._dialog.promote(self._data)

    def _on_unflag(self) -> None:
        self._dialog.unflag(self._data)


class CandidatePoolDialog(QDialog):
    """Flagged-creators outreach panel (Option A — launched from toolbar)."""

    def __init__(self, db: DatabaseManager, parent: QWidget | None = None, *, on_roster_changed=None, on_pool_changed=None) -> None:
        super().__init__(parent)
        enable_window_maximize(self)
        self._db = db
        self._on_roster_changed = on_roster_changed
        self._on_pool_changed = on_pool_changed
        self.setWindowTitle('Candidate Pool')
        self.setWindowIcon(create_app_icon())
        self.setMinimumSize(720, 480)
        self.resize(820, 600)
        self.reapply_theme()
        restore_geometry(self, 'CandidatePoolDialog', self._db)
        self.finished.connect(lambda _r: save_geometry(self, 'CandidatePoolDialog', self._db))
        self._build_ui()
        self._refresh()

    def reapply_theme(self) -> None:
        self.setStyleSheet(build_dialog_qss())

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if handle_fullscreen_keypress(self, event):
            return
        super().keyPressEvent(event)

    def _build_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(14, 14, 14, 14)
        vbox.setSpacing(10)

        title = QLabel('Candidate Pool')
        title.setObjectName('dialogTitle')
        vbox.addWidget(title)
        self._hint = QLabel('Creators you flagged from Discover. Notes are your freeform status — write whatever you want.')
        self._hint.setObjectName('hintLabel')
        vbox.addWidget(self._hint)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.viewport().setStyleSheet('background: transparent;')
        self._container = QWidget()
        self._container.setStyleSheet('background: transparent;')
        self._list_vbox = QVBoxLayout(self._container)
        self._list_vbox.setContentsMargins(2, 2, 2, 2)
        self._list_vbox.setSpacing(8)
        self._list_vbox.addStretch(1)
        self._scroll.setWidget(self._container)
        vbox.addWidget(self._scroll, 1)

        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.accept)
        vbox.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        # Clear existing rows (keep the trailing stretch).
        # takeAt() only drops the item from the layout — the widget stays
        # parented to the container and remains painted at its old spot until
        # deleteLater() runs on a later event-loop tick.  setParent(None)
        # detaches + hides it immediately, so a refresh that lands on the
        # empty state doesn't show stale rows behind the "no flagged
        # candidates" message.
        while self._list_vbox.count() > 1:
            item = self._list_vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        pool = self._db.get_candidate_pool()
        if not pool:
            empty = QLabel('No flagged candidates yet. Open Discover and flag creators worth tracking.')
            empty.setObjectName('hintLabel')
            self._list_vbox.insertWidget(0, empty)
            return
        for row in pool:
            self._list_vbox.insertWidget(self._list_vbox.count() - 1, _CandidateRow(row, self))

    # ── row callbacks ─────────────────────────────────────────────────

    def save_notes(self, channel_id: str, notes: str) -> None:
        self._db.set_candidate_notes(channel_id, notes)
        if self._on_pool_changed:
            self._on_pool_changed()

    def promote(self, data: dict) -> None:
        roles = self._db.get_roles()
        if not roles:
            dark_warning(self, 'No roles', 'Create at least one role in Settings before promoting a creator.')
            return
        new_id = self._db.promote_candidate_to_roster(data['channel_id'], roles[0]['id'])
        if new_id is None:
            dark_warning(self, 'Promotion failed', 'Creator not found in the discovered set.')
            return
        dark_info(self, 'Added to roster', f'{data.get("title", "Creator")} is now a tracked member.')
        if self._on_roster_changed:
            self._on_roster_changed()
        if self._on_pool_changed:
            self._on_pool_changed()
        self._refresh()

    def unflag(self, data: dict) -> None:
        self._db.unflag_candidate(data['channel_id'])
        if self._on_pool_changed:
            self._on_pool_changed()
        self._refresh()