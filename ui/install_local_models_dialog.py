"""Dialog for installing small local AI models into Ollama.

Offered models (Ollama tags): ``gemma3:1b``,
``qwen2.5:3b-instruct``, ``gemma3:4b``, ``qwen2.5:7b-instruct``.
The pull runs on a background :class:`PullModelWorker` so the dialog stays
responsive and shows a streaming progress bar.

Kleos does not bundle an LLM — it requires the free Ollama app to be running
locally.  When Ollama is not detected, the dialog links to ollama.com.
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6 import sip
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.db_manager import DatabaseManager
from core.local_llm import (
    PullModelWorker,
    _CANDIDATE_TAGS,
    ollama_list_installed,
)
from ui.dialog_utils import dark_question, dark_warning, enable_window_maximize
from ui.geometry import fit_to_layout_minimum, restore_geometry, save_geometry
from ui.theme import C
from ui.theme.stylesheet import build_dialog_qss

# Holds PullModelWorker instances that were cancelled as the dialog closed so
# they are not destroyed (parent deleted) while still running. Each removes
# itself on ``finished`` and schedules its own deletion. Mirrors the retire
# pattern in discover_window / history_dialog.
_RETIRING_PULL_WORKERS: set = set()


# Category label per candidate tag, shown beside the tag in the install row.
# Kept short so the row (tag + label + status + Install button) never
# truncates; the lightest-to-heaviest ordering conveys the relative weight.
_TAG_HINTS = {
    "gemma3:1b": "Best Availability",
    "qwen2.5:3b-instruct": "Best Balance",
    "gemma3:4b": "Best Value",
    "qwen2.5:7b-instruct": "Best Performance",
}

_OLLAMA_DOWNLOAD = "https://ollama.com/download"


class InstallLocalModelsDialog(QDialog):
    """Install (pull) small local models into Ollama."""

    def __init__(self, db: DatabaseManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._pull_worker: PullModelWorker | None = None
        self._active_tag: str | None = None
        self._rows: dict[str, dict[str, Any]] = {}

        self.setWindowTitle("Install Local AI Models")
        self.setMinimumWidth(480)
        enable_window_maximize(self)
        self.reapply_theme()
        restore_geometry(self, "InstallLocalModelsDialog", self._db)
        self.finished.connect(lambda _r: save_geometry(self, "InstallLocalModelsDialog", self._db))

        root = QVBoxLayout(self)
        root.setSpacing(12)

        title = QLabel("Install Local AI Models")
        title.setObjectName("dialogTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        intro = QLabel(
            "Kleos runs local models through Ollama — a free app you install "
            "separately. Pick a model below to download it into Ollama; once "
            "installed it appears in the model dropdown and can be used for "
            "AI Verify and Discover Evaluate, fully offline."
        )
        intro.setObjectName("hintLabel")
        intro.setWordWrap(True)
        root.addWidget(intro)

        self._link = QLabel(f'<a href="{_OLLAMA_DOWNLOAD}">{_OLLAMA_DOWNLOAD}</a>')
        self._link.setObjectName("hintLabel")
        self._link.setOpenExternalLinks(True)
        self._link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        root.addWidget(self._link)

        # Ollama status row.
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self._ollama_label = QLabel()
        self._ollama_label.setObjectName("hintLabel")
        status_row.addWidget(self._ollama_label)
        status_row.addStretch(1)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._refresh_status)
        status_row.addWidget(self._refresh_btn)
        root.addLayout(status_row)

        # Pull progress widgets (hidden until a pull starts).
        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        root.addWidget(self._progress_bar)
        self._progress_label = QLabel()
        self._progress_label.setObjectName("hintLabel")
        self._progress_label.setVisible(False)
        root.addWidget(self._progress_label)

        # One row per candidate model.
        for tag in _CANDIDATE_TAGS:
            root.addLayout(self._build_tag_row(tag))

        root.addStretch(1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self._on_close)
        root.addWidget(close_btn)

        self._refresh_status()

        # The layout was built after restore_geometry, so a stale (shorter)
        # saved geometry from the old 3-row layout can be below the new 4-row
        # minimum. Grow to the layout's minimum height (keeping the saved
        # width/position) so Qt doesn't log "Unable to set geometry" on show.
        fit_to_layout_minimum(self)

    def _build_tag_row(self, tag: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        hint = _TAG_HINTS.get(tag, "")
        name = QLabel(f"{tag}  —  {hint}")
        name.setObjectName("formLabel")
        row.addWidget(name, 1)
        status = QLabel("Checking…")
        status.setObjectName("hintLabel")
        row.addWidget(status)
        install_btn = QPushButton("Install")
        install_btn.clicked.connect(lambda _checked=False, t=tag: self._on_install(t))
        row.addWidget(install_btn)
        self._rows[tag] = {"status": status, "btn": install_btn}
        return row

    # ── Status ────────────────────────────────────────────────────────

    def reapply_theme(self) -> None:
        self.setStyleSheet(build_dialog_qss())

    def _set_row_status(self, tag: str, text: str, color: str, btn_enabled: bool, btn_text: str = "Install") -> None:
        row = self._rows.get(tag)
        if not row:
            return
        row["status"].setStyleSheet(f"color: {color};")
        row["status"].setText(text)
        row["btn"].setEnabled(btn_enabled)
        row["btn"].setText(btn_text)

    def _refresh_status(self) -> None:
        """Query Ollama and update the status of every row."""
        installed, err = ollama_list_installed(self._db)
        if err:
            self._ollama_label.setText("Ollama: not detected")
            self._ollama_label.setStyleSheet(f"color: {C.DANGER};")
            for tag in _CANDIDATE_TAGS:
                self._set_row_status(tag, "Ollama not detected", C.DANGER, btn_enabled=False)
            return
        self._ollama_label.setText("Ollama: running")
        self._ollama_label.setStyleSheet(f"color: {C.SUCCESS};")
        installed_set = set(installed)
        for tag in _CANDIDATE_TAGS:
            if tag in installed_set:
                self._set_row_status(tag, "Installed", C.SUCCESS, btn_enabled=False, btn_text="Installed ✓")
            else:
                self._set_row_status(tag, "Not installed", C.TEXT_MUTED, btn_enabled=True)

    # ── Install / pull ────────────────────────────────────────────────

    def _on_install(self, tag: str) -> None:
        # Disable all install buttons + refresh while a pull is running.
        for t in _CANDIDATE_TAGS:
            self._rows[t]["btn"].setEnabled(False)
        self._refresh_btn.setEnabled(False)
        self._active_tag = tag
        self._set_row_status(tag, "Installing…", C.TEXT_MUTED, btn_enabled=False)
        self._progress_bar.setRange(0, 0)  # indeterminate until a % arrives
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._progress_label.setText("Preparing…")
        self._progress_label.setVisible(True)

        self._pull_worker = PullModelWorker(tag, db=self._db)
        self._pull_worker.progress.connect(self._on_pull_progress)
        self._pull_worker.done.connect(self._on_pull_done)
        self._pull_worker.error.connect(self._on_pull_error)
        self._pull_worker.aborted.connect(self._on_pull_aborted)
        self._pull_worker.finished.connect(self._on_pull_finished)
        self._pull_worker.start()

    def _on_pull_finished(self) -> None:
        """Clear the worker reference once it has fully finished.

        ``done``/``error``/``aborted`` fire *before* ``finished``; clearing the
        ref here (rather than in those handlers) keeps the worker alive for the
        duration of its signal emission and means ``closeEvent``'s
        ``sip.isdeleted`` guard never sees a half-deleted QThread.
        """
        w = self._pull_worker
        self._pull_worker = None
        self._active_tag = None
        if w is not None and not sip.isdeleted(w):
            w.deleteLater()

    def _on_pull_progress(self, text: str, percent: int) -> None:
        if percent >= 0:
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(percent)
            self._progress_label.setText(f"{text} ({percent}%)")
        else:
            self._progress_bar.setRange(0, 0)
            self._progress_label.setText(text)

    def _on_pull_done(self, tag: str) -> None:
        self._hide_progress()
        self._refresh_btn.setEnabled(True)
        self._active_tag = None
        self._refresh_status()

    def _on_pull_error(self, msg: str) -> None:
        self._hide_progress()
        if self._active_tag is not None:
            self._set_row_status(self._active_tag, f"Failed: {msg}", C.DANGER, btn_enabled=True)
        self._refresh_btn.setEnabled(True)
        self._active_tag = None
        dark_warning(self, "Install Failed", msg)

    def _on_pull_aborted(self) -> None:
        self._hide_progress()
        self._refresh_btn.setEnabled(True)
        self._active_tag = None
        self._refresh_status()

    def _hide_progress(self) -> None:
        self._progress_bar.setVisible(False)
        self._progress_label.setVisible(False)

    # ── Close ─────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        self.close()

    def closeEvent(self, event) -> None:
        # Guard against the worker having already finished and been deleted
        # by the finished-slot's deleteLater — calling isRunning() on a deleted
        # QThread raises RuntimeError.
        w = self._pull_worker
        if w is not None and not sip.isdeleted(w) and w.isRunning():
            result = dark_question(
                self, "Cancel Download",
                "A model is still downloading. Cancel the in-progress download?",
            )
            if result != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            # Retire instead of wait()ing on the GUI thread (which would freeze
            # the dialog up to 3s). The worker is unparented so the dialog close
            # can't destroy it mid-run; it self-deletes on finished.
            w.cancel()
            _RETIRING_PULL_WORKERS.add(w)
            # Disconnect GUI-mutating signals so a late emit can't touch the
            # dying dialog, but keep ``finished`` for the cleanup lambda.
            for name in ('progress', 'done', 'error', 'aborted'):
                try:
                    getattr(w, name).disconnect()
                except (TypeError, RuntimeError):
                    pass
            try:
                w.finished.connect(lambda *_: (_RETIRING_PULL_WORKERS.discard(w), w.deleteLater()))
            except (TypeError, RuntimeError):
                pass
            # Race guard: if it finished between isRunning() and the connect,
            # clean up directly so it can't leak in the set.
            if not w.isRunning():
                _RETIRING_PULL_WORKERS.discard(w)
                try:
                    if not sip.isdeleted(w):
                        w.deleteLater()
                except (RuntimeError, TypeError):
                    pass
            self._pull_worker = None
        super().closeEvent(event)