from __future__ import annotations
import json
from typing import Any
from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QColorDialog, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QTabWidget, QTextEdit, QVBoxLayout, QWidget
from PyQt6.QtGui import QColor
from core.db_manager import DatabaseManager
from core.cache_manager import clear_untracked_thumbnails
from core.local_llm import get_ollama_host, ListLocalModelsWorker
from ui.dialog_utils import dark_info, dark_question, dark_warning
from ui.install_local_models_dialog import InstallLocalModelsDialog
from ui.verify_dialog import _PROVIDERS as _VERIFY_PROVIDERS
from ui.discover_window import _SHORTS_MODES, _SORTS
from ui.geometry import restore_geometry, save_geometry
from ui.theme.stylesheet import build_dialog_qss, qss_refresh
from ui.theme.tokens import C, theme_manager, THEMES, THEME_NAMES
class _ApiKeysTab(QWidget):
    """Input fields for YouTube Data API v3 and Twitch Helix credentials."""
    def __init__(self, db: DatabaseManager, parent: QWidget | None=None) -> None:
        super().__init__(parent)
        self._db = db
        layout = QVBoxLayout(self)
        form = QFormLayout()
        keys = db.get_api_keys()
        self._yt_key = QLineEdit(keys.get('youtube', ''))
        self._yt_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._yt_key.setPlaceholderText('AIza...')
        form.addRow('YouTube API Key:', self._yt_key)
        self._twitch_cid = QLineEdit(keys.get('twitch_client_id', ''))
        self._twitch_cid.setPlaceholderText('Client ID')
        form.addRow('Twitch Client ID:', self._twitch_cid)
        self._twitch_secret = QLineEdit(keys.get('twitch_client_secret', ''))
        self._twitch_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self._twitch_secret.setPlaceholderText('Client Secret')
        form.addRow('Twitch Client Secret:', self._twitch_secret)
        self._anthropic_key = QLineEdit(keys.get('anthropic', ''))
        self._anthropic_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._anthropic_key.setPlaceholderText('sk-ant-…')
        form.addRow('Anthropic API Key:', self._anthropic_key)
        self._gemini_key = QLineEdit(keys.get('gemini', ''))
        self._gemini_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._gemini_key.setPlaceholderText('AIzaSy…')
        form.addRow('Gemini API Key:', self._gemini_key)
        layout.addLayout(form)
        layout.addSpacing(12)
        limit_label = QLabel('Videos per creator:')
        limit_label.setObjectName('formLabel')
        layout.addWidget(limit_label)
        limit_hint = QLabel('Maximum videos to fetch per creator. Set to 0 for all.')
        limit_hint.setObjectName('noteLabel')
        limit_hint.setWordWrap(True)
        layout.addWidget(limit_hint)
        self._limit_spin = QSpinBox()
        self._limit_spin.setRange(0, 9999)
        saved_limit = db.get_setting('fetch_video_limit') or '50'
        try:
            self._limit_spin.setValue(int(saved_limit))
        except (ValueError, TypeError):
            self._limit_spin.setValue(50)
        self._limit_spin.setSpecialValueText('All')
        layout.addWidget(self._limit_spin)
        layout.addStretch(1)
        note = QLabel('API keys are shared across all profiles.')
        note.setObjectName('noteLabel')
        note.setWordWrap(True)
        layout.addWidget(note)
    def save(self) -> None:
        yt_key = self._yt_key.text().strip()
        twitch_cid = self._twitch_cid.text().strip()
        twitch_secret = self._twitch_secret.text().strip()
        anthropic_key = self._anthropic_key.text().strip()
        gemini_key = self._gemini_key.text().strip()
        # Load existing keys so we can preserve them on validation failure
        existing = self._db.get_api_keys()
        # Validate YouTube key: only update if valid; warn but preserve old value if invalid
        if yt_key:
            if not yt_key.startswith('AIza'):
                dark_warning(self, 'Invalid YouTube Key', 'YouTube API keys must start with \'AIza\'.\nThe YouTube key was not saved; your previous key is preserved.')
                yt_key = existing.get('youtube', '')
            elif len(yt_key) != 39:
                dark_warning(self, 'YouTube Key Warning', f'YouTube API keys are typically 39 characters long (got {len(yt_key)}).\nSaving anyway — verify your key works.')
        keys = {'youtube': yt_key, 'twitch_client_id': twitch_cid, 'twitch_client_secret': twitch_secret, 'anthropic': anthropic_key, 'gemini': gemini_key}
        self._db.set_api_keys(keys)
        self._db.set_setting('fetch_video_limit', str(self._limit_spin.value()))
class _VerifyTab(QWidget):
    """Community description, AI model selection, and keyword verification settings."""
    _MAX_WORDS = 300
    @staticmethod
    def _base_models() -> list[tuple[str, str]]:
        """Cloud models, sourced from the single verify-dialog provider list.

        Returns ``(label, model_id)`` pairs.  Deriving from
        ``_VERIFY_PROVIDERS`` keeps the IDs in sync with the Verify dialog and
        the Discover combo (one source of truth) and avoids the swapped-tuple
        drift a separate hand-maintained list would risk.  Providers are
        iterated in a fixed order so the combo keeps its Claude-then-Gemini
        ordering regardless of dict insertion order.
        """
        models: list[tuple[str, str]] = []
        for key in ('claude', 'gemini'):
            prov = _VERIFY_PROVIDERS[key]
            for mid, short, desc in prov['models']:
                models.append((f"{prov['label']} {short} ({desc})", mid))
        return models
    def _populate_cloud_models(self, saved_model: str | None = None) -> None:
        """Fill the combo with cloud models instantly (no network)."""
        self._model_combo.clear()
        saved = saved_model or (self._db.get_setting('auto_verify_model') or 'claude-haiku-4-5-20251001')
        for i, (label, model_id) in enumerate(self._base_models()):
            self._model_combo.addItem(label, model_id)
            if model_id == saved:
                self._model_combo.setCurrentIndex(i)
    def _apply_local_models(self, tags: list[str]) -> None:
        """Append/replace the local-model portion of the combo without
        disturbing the cloud selection.

        ``tags`` is the list of bare Ollama tags (empty when Ollama is off or
        has no models installed).  The user's current selection is preserved
        only if it still exists afterwards.
        """
        if sip.isdeleted(self) or sip.isdeleted(self._model_combo):
            return
        current = self._model_combo.currentData()
        # Drop any previously-appended local entries.
        i = 0
        while i < self._model_combo.count():
            data = self._model_combo.itemData(i)
            if isinstance(data, str) and data.startswith('ollama:'):
                self._model_combo.removeItem(i)
            else:
                i += 1
        for tag in tags:
            self._model_combo.addItem(f"{tag} (local)", f"ollama:{tag}")

        if self._auto_select_saved_local:
            # First load: honour a saved local model now that it's available.
            self._auto_select_saved_local = False
            saved = self._db.get_setting('auto_verify_model')
            if saved and saved.startswith('ollama:'):
                for j in range(self._model_combo.count()):
                    if self._model_combo.itemData(j) == saved:
                        self._model_combo.setCurrentIndex(j)
                        return
                # Saved local model not installed — fall through to preserve
                # the cloud fallback already set by _populate_cloud_models.

        # Preserve the current selection (saved cloud model set by
        # _populate_cloud_models, or a deliberate pick made while the tab was
        # open) only if it still exists afterwards.
        if current:
            for j in range(self._model_combo.count()):
                if self._model_combo.itemData(j) == current:
                    self._model_combo.setCurrentIndex(j)
                    break
    def _refresh_local_models_async(self) -> None:
        """Fetch installed local models off the GUI thread and apply them
        when Ollama responds.  If a fetch is already in flight, queue another
        for when it finishes so a refresh requested mid-fetch isn't lost.
        """
        if self._list_worker is not None:
            self._pending_refresh = True
            return
        worker = ListLocalModelsWorker(get_ollama_host(self._db))
        self._list_worker = worker
        worker.done.connect(self._on_local_models_done)
        worker.error.connect(self._on_local_models_error)
        worker.finished.connect(self._retire_list_worker)
        worker.start()
    def _on_local_models_done(self, tags: list) -> None:
        if sip.isdeleted(self) or sip.isdeleted(self._model_combo):
            return
        self._apply_local_models(list(tags))
    def _on_local_models_error(self, _msg: str) -> None:
        if sip.isdeleted(self) or sip.isdeleted(self._model_combo):
            return
        self._apply_local_models([])
    def _retire_list_worker(self) -> None:
        self._list_worker = None
        if self._pending_refresh:
            self._pending_refresh = False
            self._refresh_local_models_async()
    def __init__(self, db: DatabaseManager, parent: QWidget | None=None) -> None:
        super().__init__(parent)
        self._db = db
        self._list_worker: ListLocalModelsWorker | None = None
        self._pending_refresh = False
        # On the very first async local-model load we re-select the saved model
        # if it's a local one (matching the old synchronous populate, which
        # selected saved cloud-or-local in one go). Subsequent refreshes
        # (tab re-show, post-install) only preserve the user's current pick —
        # we never override a deliberate selection made while the tab was open.
        self._auto_select_saved_local = True
        layout = QVBoxLayout(self)
        name_label = QLabel('Community Name:')
        name_label.setObjectName('formLabel')
        layout.addWidget(name_label)
        name_hint = QLabel(
            'A short name for your community (e.g. "ArchMC"). Used as the '
            'query for media-coverage searches and as a fallback when you '
            'run Discover without entering keywords.'
        )
        name_hint.setObjectName('hintLabel')
        name_hint.setWordWrap(True)
        layout.addWidget(name_hint)
        self._name_edit = QLineEdit()
        self._name_edit.setText(db.get_setting('community_name') or '')
        self._name_edit.setPlaceholderText('e.g. ArchMC')
        layout.addWidget(self._name_edit)
        layout.addSpacing(12)
        desc_label = QLabel('Community Description:')
        desc_label.setObjectName('formLabel')
        layout.addWidget(desc_label)
        desc_hint = QLabel(
            f'Describe your community in {_VerifyTab._MAX_WORDS} words or fewer. '
            'The AI will use this to decide which videos to verify.'
        )
        desc_hint.setObjectName('hintLabel')
        desc_hint.setWordWrap(True)
        layout.addWidget(desc_hint)
        self._desc_edit = QTextEdit()
        saved_desc = db.get_setting('community_description') or ''
        self._desc_edit.setPlainText(saved_desc)
        self._desc_edit.setAcceptRichText(False)
        self._desc_edit.setPlaceholderText(
            'e.g. A Minecraft survival community focused on redstone engineering '
            'and collaborative building projects…'
        )
        self._desc_edit.setMaximumHeight(160)
        self._desc_edit.textChanged.connect(self._update_word_count)
        layout.addWidget(self._desc_edit)
        self._word_label = QLabel()
        self._word_label.setObjectName('wordCount')
        self._update_word_count()
        layout.addWidget(self._word_label)
        layout.addSpacing(12)
        model_label = QLabel('AI Model:')
        model_label.setObjectName('formLabel')
        layout.addWidget(model_label)
        self._model_combo = QComboBox()
        model_row = QHBoxLayout()
        model_row.setSpacing(8)
        model_row.addWidget(self._model_combo, 1)
        self._install_local_btn = QPushButton('Install Local AI Models')
        self._install_local_btn.setToolTip(
            "Download a small AI model that runs locally via Ollama — no "
            "cloud API key needed. Requires the free Ollama app."
        )
        self._install_local_btn.clicked.connect(self._on_install_local_models)
        model_row.addWidget(self._install_local_btn)
        layout.addLayout(model_row)
        # Cloud models populate instantly; installed local models are fetched
        # off the GUI thread and appended when Ollama responds so opening this
        # tab never blocks on a network round-trip.
        self._populate_cloud_models()
        self._refresh_local_models_async()
        layout.addSpacing(12)
        kw_label = QLabel('Verification Keywords:')
        kw_label.setObjectName('formLabel')
        layout.addWidget(kw_label)
        kw_hint = QLabel(
            'Enter keywords separated by commas. Videos whose title or description '
            'contain any keyword as a whole word will be auto-verified. '
            'Matching is case-insensitive. This does not use AI.'
        )
        kw_hint.setObjectName('hintLabel')
        kw_hint.setWordWrap(True)
        layout.addWidget(kw_hint)
        self._keywords_edit = QLineEdit()
        saved_keywords = db.get_setting('verify_keywords') or ''
        self._keywords_edit.setText(saved_keywords)
        self._keywords_edit.setPlaceholderText('e.g. arch.mc, ArchMC, ArchMC Network, mc.arch.lol')
        layout.addWidget(self._keywords_edit)
        layout.addStretch(1)
    def _on_install_local_models(self) -> None:
        """Open the local-model installer, then refresh the model dropdown."""
        dlg = InstallLocalModelsDialog(self._db, self)
        dlg.exec()
        # A model may have been installed/removed — re-fetch the installed set
        # off the GUI thread.  The user's current (possibly unsaved) selection
        # is preserved by _apply_local_models.
        self._refresh_local_models_async()

    def showEvent(self, event) -> None:
        # Reflect the current Ollama state each time the tab is shown — fetched
        # off the GUI thread so the tab opens instantly.  The cloud combo is
        # already built in __init__; this only refreshes the local entries.
        self._refresh_local_models_async()
        super().showEvent(event)

    def _update_word_count(self) -> None:
        text = self._desc_edit.toPlainText()
        word_count = len(text.split()) if text.strip() else 0
        over = word_count > _VerifyTab._MAX_WORDS
        self._word_label.setText(f'{word_count} / {_VerifyTab._MAX_WORDS} words')
        self._word_label.setProperty('over', 'true' if over else 'false')
        qss_refresh(self._word_label)
    def validate(self) -> bool:
        """Check inputs without writing. Returns False (with a warning) if the
        community description exceeds the word limit."""
        text = self._desc_edit.toPlainText().strip()
        word_count = len(text.split()) if text else 0
        if word_count > _VerifyTab._MAX_WORDS:
            dark_warning(
                self, 'Too Many Words',
                f'Community description must be {_VerifyTab._MAX_WORDS} words or fewer (got {word_count}).'
            )
            return False
        return True
    def save(self) -> bool:
        if not self.validate():
            return False
        text = self._desc_edit.toPlainText().strip()
        self._db.set_setting('community_description', text)
        self._db.set_setting('community_name', self._name_edit.text().strip())
        self._db.set_setting('auto_verify_model', self._model_combo.currentData())
        self._db.set_setting('verify_keywords', self._keywords_edit.text().strip())
        return True
class _ProfilesTab(QWidget):
    """Create, rename, and switch between database profiles."""
    def __init__(self, db: DatabaseManager, parent: QWidget | None=None, cancel_fetch: Any=None) -> None:
        super().__init__(parent)
        self._db = db
        self._profile_changed = False
        self._cancel_fetch = cancel_fetch
        # A profile switch/create requested inside the dialog but not yet
        # committed.  The actual switch_profile() call is deferred to save()
        # so that the other tabs (which still hold the *previous* profile's
        # values) write to the previous profile first, instead of overwriting
        # the new profile with stale data.
        self._pending_profile: str | None = None
        layout = QVBoxLayout(self)
        h_current = QHBoxLayout()
        h_current.addWidget(QLabel('Active Profile:'))
        self._current_label = QLabel(db.profile)
        self._current_label.setObjectName('accentLabel')
        h_current.addWidget(self._current_label)
        h_current.addStretch(1)
        layout.addLayout(h_current)
        self._list = QListWidget()
        self._refresh_list()
        layout.addWidget(self._list)
        btn_row = QHBoxLayout()
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText('New profile name…')
        btn_row.addWidget(self._name_input, 1)
        create_btn = QPushButton('Create')
        create_btn.clicked.connect(self._on_create)
        btn_row.addWidget(create_btn)
        switch_btn = QPushButton('Switch To')
        switch_btn.clicked.connect(self._on_switch)
        btn_row.addWidget(switch_btn)
        delete_btn = QPushButton('Delete')
        delete_btn.setObjectName('danger')
        delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(delete_btn)
        layout.addLayout(btn_row)
        layout.addSpacing(12)
        io_row = QHBoxLayout()
        export_btn = QPushButton('Export Profile')
        export_btn.clicked.connect(self._on_export)
        io_row.addWidget(export_btn)
        import_btn = QPushButton('Import Profile')
        import_btn.clicked.connect(self._on_import)
        io_row.addWidget(import_btn)
        import_creator_btn = QPushButton('Import Creator')
        import_creator_btn.clicked.connect(self._on_import_creator)
        io_row.addWidget(import_creator_btn)
        io_row.addStretch(1)
        layout.addLayout(io_row)
        backup_row = QHBoxLayout()
        clear_backups_btn = QPushButton('Clear Backups')
        clear_backups_btn.setObjectName('danger')
        clear_backups_btn.setToolTip(
            'Delete all stored profile backup files from the AppData storage '
            'folder. This frees disk space but removes the automatic '
            'point-in-time backups; new backups are created on future changes.')
        clear_backups_btn.clicked.connect(self._on_clear_backups)
        backup_row.addWidget(clear_backups_btn)
        backup_row.addStretch(1)
        layout.addLayout(backup_row)
        layout.addStretch(1)
    def _refresh_list(self) -> None:
        self._list.clear()
        current = self._pending_profile or self._db.profile
        names = self._db.list_profiles()
        # A pending create has no database yet, so show it in the list
        # (bolded) so the user sees their choice before it is committed.
        if self._pending_profile and self._pending_profile not in names:
            names = names + [self._pending_profile]
        for name in names:
            item = QListWidgetItem(name)
            if name == current:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self._list.addItem(item)
    def _on_create(self) -> None:
        name = self._name_input.text().strip().lower()
        if not name:
            return None
        else:
            if not name.replace('_', '').replace('-', '').isalnum():
                dark_warning(self, 'Invalid Name', 'Use only letters, numbers, hyphens, and underscores.')
                return None
            else:
                existing = self._db.list_profiles()
                if name in existing:
                    dark_warning(self, 'Exists', f'Profile \'{name}\' already exists.')
                    return None
                else:
                    if self._cancel_fetch:
                        self._cancel_fetch()
                    self._pending_profile = name
                    self._profile_changed = True
                    self._current_label.setText(name)
                    self._name_input.clear()
                    self._refresh_list()
    def _on_switch(self) -> None:
        item = self._list.currentItem()
        if not item:
            return None
        else:
            name = item.text()
            if name == (self._pending_profile or self._db.profile):
                return None
            else:
                if self._cancel_fetch:
                    self._cancel_fetch()
                self._pending_profile = name
                self._profile_changed = True
                self._current_label.setText(name)
                self._refresh_list()
    def _on_delete(self) -> None:
        item = self._list.currentItem()
        if not item:
            return None
        else:
            name = item.text()
            if name == self._db.profile:
                dark_warning(self, 'Cannot Delete', 'Cannot delete the active profile.')
                return None
            else:
                confirm = dark_question(self, 'Delete Profile', f'Permanently delete profile \'{name}\' and all its data?')
                if confirm == QMessageBox.StandardButton.Yes:
                    try:
                        self._db.delete_profile(name)
                    except ValueError as exc:
                        dark_warning(self, 'Cannot Delete', str(exc))
                        return
                    self._refresh_list()

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export Profile', f'{self._db.profile}.json', 'JSON Files (*.json)')
        if not path:
            return
        try:
            data = self._db.export_profile()
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            dark_info(self, 'Exported', f'Profile exported to {path}')
        except Exception as exc:
            dark_warning(self, 'Export Failed', str(exc))

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, 'Import Profile', '', 'JSON Files (*.json)')
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            dark_warning(self, 'Import Failed', f'Invalid file: {exc}')
            return
        if data.get('version') != 1:
            dark_warning(self, 'Invalid File', 'Unsupported profile format version.')
            return
        name = data.get('profile', 'imported')
        existing = self._db.list_profiles()
        if name in existing:
            i = 1
            while f'{name}_{i}' in existing:
                i += 1
            name = f'{name}_{i}'
        try:
            self._db.import_profile(data, name)
        except Exception as exc:
            dark_warning(self, 'Import Failed', str(exc))
            return
        if self._cancel_fetch:
            self._cancel_fetch()
        self._profile_changed = True
        self._current_label.setText(name)
        self._name_input.clear()
        self._refresh_list()
        dark_info(self, 'Imported', f'Profile "{name}" imported successfully.')

    def _on_clear_backups(self) -> None:
        """Delete all stored profile backup files from the AppData folder."""
        result = dark_question(
            self, 'Clear Backups',
            'This permanently deletes all stored profile backup files from '
            'the AppData storage folder. New backups will be created '
            'automatically on future changes.\n\nContinue?')
        if result != QMessageBox.StandardButton.Yes:
            return
        removed = self._db.clear_backups()
        dark_info(self, 'Backups Cleared', f'Deleted {removed} backup file(s).')

    def _on_import_creator(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, 'Import Creator', '', 'JSON Files (*.json)')
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            dark_warning(self, 'Import Failed', f'Invalid file: {exc}')
            return
        if data.get('type') != 'creator':
            dark_warning(self, 'Invalid File', 'This file is not a creator export.')
            return
        try:
            new_id = self._db.import_creator(data)
        except Exception as exc:
            dark_warning(self, 'Import Failed', str(exc))
            return
        dark_info(self, 'Imported', f'Creator imported successfully (ID: {new_id}).')

    def save(self) -> bool:
        """Commit a deferred profile switch/create.

        Called from ``SettingsDialog._on_save`` *after* the other tabs have
        persisted their values, so those tabs write to the previous profile
        rather than overwriting the new one with stale data.  Returns False
        if the switch could not be completed (e.g. the profile name is no
        longer valid), leaving the active profile unchanged.
        """
        if self._pending_profile is None:
            return True
        try:
            self._db.switch_profile(self._pending_profile)
        except ValueError as exc:
            dark_warning(self, 'Cannot Switch Profile', str(exc))
            return False
        self._pending_profile = None
        return True

    @property
    def profile_changed(self) -> bool:
        return self._profile_changed
class _RoleManagerTab(QWidget):
    """Create and delete custom roles with color picker."""
    def __init__(self, db: DatabaseManager, parent: QWidget | None=None) -> None:
        super().__init__(parent)
        self._db = db
        self._changed = False
        layout = QVBoxLayout(self)
        self._list = QListWidget()
        self._list.setMaximumHeight(200)
        self._refresh_list()
        layout.addWidget(self._list)
        form = QHBoxLayout()
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText('Role name…')
        form.addWidget(self._name_input, 1)
        self._color_hex = QLineEdit(C.ACCENT)
        self._color_hex.setFixedWidth(90)
        self._color_hex.setAlignment(Qt.AlignmentFlag.AlignCenter)
        form.addWidget(self._color_hex)
        pick_btn = QPushButton('Pick Color')
        pick_btn.setFixedWidth(90)
        pick_btn.clicked.connect(self._pick_color)
        form.addWidget(pick_btn)
        add_btn = QPushButton('Add Role')
        add_btn.clicked.connect(self._on_add)
        form.addWidget(add_btn)
        layout.addLayout(form)
        del_btn = QPushButton('Delete Selected Role')
        del_btn.setObjectName('danger')
        del_btn.clicked.connect(self._on_delete)
        layout.addWidget(del_btn)
        edit_btn = QPushButton('Edit Selected Role')
        edit_btn.clicked.connect(self._on_edit)
        layout.addWidget(edit_btn)
        clear_btn = QPushButton('Clear Cache')
        clear_btn.setToolTip(
            'Delete cached video thumbnails and profile pictures that are no '
            'longer tracked by any profile. Files still in use — including '
            'those tracked by other profiles — are kept. Removed files are '
            're-downloaded on the next fetch if needed.')
        clear_btn.clicked.connect(self._on_clear_cache)
        layout.addWidget(clear_btn)
        layout.addStretch(1)
    def _refresh_list(self) -> None:
        self._list.clear()
        for role in self._db.get_roles():
            text = f"{role['role_name']}  ● {role['role_color']}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, role['id'])
            self._list.addItem(item)
    def _on_clear_cache(self) -> None:
        """Delete cached thumbnails/PFPs not tracked by any profile."""
        result = dark_question(
            self, 'Clear Cache',
            'This deletes cached video thumbnails and profile pictures that '
            'are no longer tracked by any profile. Files still in use — '
            'including those tracked by other profiles — are kept. Removed '
            'files are re-downloaded on the next fetch if needed.\n\nContinue?')
        if result != QMessageBox.StandardButton.Yes:
            return
        removed = clear_untracked_thumbnails(self._db)
        dark_info(
            self, 'Cache Cleared',
            f'Deleted {removed} untracked cached image file(s).')
    def _pick_color(self) -> None:
        current = QColor(self._color_hex.text())
        if not current.isValid():
            current = QColor(C.ACCENT)
        color = QColorDialog.getColor(current, self, 'Choose Role Color')
        if color.isValid():
            self._color_hex.setText(color.name())
    def _on_add(self) -> None:
        name = self._name_input.text().strip()
        color = self._color_hex.text().strip()
        if not name:
            dark_warning(self, 'Missing Name', 'Enter a role name.')
            return None
        else:
            if not QColor(color).isValid():
                dark_warning(self, 'Invalid Color', 'Choose a valid hex color.')
                return None
            else:
                try:
                    self._db.add_role(name, color)
                except ValueError:
                    dark_warning(self, 'Duplicate', f'Role \'{name}\' already exists.')
                    return None
                self._changed = True
                self._name_input.clear()
                self._refresh_list()
    def _on_delete(self) -> None:
        item = self._list.currentItem()
        if not item:
            return None
        else:
            role_id = item.data(Qt.ItemDataRole.UserRole)
            creators = self._db.get_creators()
            in_use = [c['nickname'] for c in creators if c.get('role_id') == role_id]
            if in_use:
                dark_warning(self, 'Role In Use', f'Cannot delete — assigned to: {', '.join(in_use)}')
                return None
            else:
                self._db.delete_role(role_id)
                self._changed = True
                self._refresh_list()

    def _on_edit(self) -> None:
        """Open a dialog to edit the selected role's name and color."""
        item = self._list.currentItem()
        if not item:
            return
        role_id = item.data(Qt.ItemDataRole.UserRole)
        role = self._db.get_role(role_id)
        if not role:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle('Edit Role')
        dlg.setMinimumWidth(300)
        dlg.setStyleSheet(build_dialog_qss())
        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        name_edit = QLineEdit(role['role_name'])
        color_hex = QLineEdit(role['role_color'])
        color_hex.setFixedWidth(90)
        color_hex.setAlignment(Qt.AlignmentFlag.AlignCenter)
        form.addRow('Name:', name_edit)
        color_row = QHBoxLayout()
        color_row.addWidget(color_hex, 1)
        pick_btn = QPushButton('Pick Color')
        pick_btn.setFixedWidth(90)
        def pick():
            current = QColor(color_hex.text())
            if not current.isValid():
                current = QColor(C.ACCENT)
            color = QColorDialog.getColor(current, dlg, 'Choose Role Color')
            if color.isValid():
                color_hex.setText(color.name())
        pick_btn.clicked.connect(pick)
        color_row.addWidget(pick_btn)
        form.addRow('Color:', color_row)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_name = name_edit.text().strip()
            new_color = color_hex.text().strip()
            if not new_name:
                dark_warning(self, 'Missing Name', 'Enter a role name.')
                return
            if not QColor(new_color).isValid():
                dark_warning(self, 'Invalid Color', 'Choose a valid hex color.')
                return
            self._db.update_role(role_id, role_name=new_name, role_color=new_color)
            self._changed = True
            self._refresh_list()
    @property
    def changed(self) -> bool:
        return self._changed
class _AppearanceTab(QWidget):
    """Appearance settings: theme selector and thumbnail quality toggle."""
    def __init__(self, db: DatabaseManager, parent: QWidget | None=None) -> None:
        super().__init__(parent)
        self._db = db
        layout = QVBoxLayout(self)

        # ── Theme selector ────────────────────────────────────────────
        theme_label = QLabel('Theme:')
        theme_label.setObjectName('formLabel')
        layout.addWidget(theme_label)

        self._theme_combo = QComboBox()
        for key, name in THEME_NAMES.items():
            self._theme_combo.addItem(name, key)
        saved_theme = db.get_setting('theme') or 'default'
        idx = self._theme_combo.findData(saved_theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        self._theme_combo.currentIndexChanged.connect(self._update_preview)
        layout.addWidget(self._theme_combo)

        self._theme_preview = QLabel()
        self._theme_preview.setWordWrap(True)
        self._update_preview()
        layout.addWidget(self._theme_preview)

        layout.addSpacing(16)

        # ── Thumbnail quality ─────────────────────────────────────────
        thumb_label = QLabel('Thumbnail Quality:')
        thumb_label.setObjectName('formLabel')
        layout.addWidget(thumb_label)
        self._thumb_combo = QComboBox()
        self._thumb_combo.addItem('Low (cached)', 'low')
        self._thumb_combo.addItem('High (re-fetch)', 'high')
        saved = db.get_setting('thumbnail_quality') or 'low'
        idx = self._thumb_combo.findData(saved)
        if idx >= 0:
            self._thumb_combo.setCurrentIndex(idx)
        layout.addWidget(self._thumb_combo)
        thumb_hint = QLabel(
            'Low quality uses cached thumbnails (fast).\n'
            'High quality re-downloads thumbnails from original URLs (slower, better resolution).'
        )
        thumb_hint.setObjectName('noteLabel')
        thumb_hint.setWordWrap(True)
        layout.addWidget(thumb_hint)
        layout.addStretch(1)

    def _update_preview(self) -> None:
        """Update the colour-swatch preview when the theme selection changes."""
        key = self._theme_combo.currentData()
        if not key or key not in THEMES:
            return
        t = THEMES[key]
        self._theme_preview.setText(
            f'<span style="color:{t["ACCENT"]}">■</span> Accent '
            f'<span style="color:{t["TEXT_PRIMARY"]}">■</span> Text '
            f'<span style="color:{t["DANGER"]}">■</span> Danger '
            f'<span style="color:{t["SUCCESS"]}">■</span> Success '
            f'<span style="color:{t["BG_DEEP"]}">■</span> Deep '
            f'<span style="color:{t["BG_RAISED"]}">■</span> Raised'
        )

    def save(self) -> None:
        self._db.set_setting('theme', self._theme_combo.currentData())
        self._db.set_setting('thumbnail_quality', self._thumb_combo.currentData())


class _NotificationsTab(QWidget):
    """Notification settings: view count thresholds and subscriber milestones."""
    def __init__(self, db: DatabaseManager, parent: QWidget | None=None) -> None:
        super().__init__(parent)
        self._db = db
        layout = QVBoxLayout(self)

        # Master notifications toggle (off by default)
        self._enabled_check = QCheckBox('Enable notifications')
        self._enabled_check.setChecked((db.get_setting('notifications_enabled') or '0') == '1')
        self._enabled_check.setToolTip('When off, no milestone, rapid-growth, or inactivity alerts are shown.')
        layout.addWidget(self._enabled_check)

        layout.addSpacing(16)

        # View count thresholds
        view_label = QLabel('View Count Alert Thresholds:')
        view_label.setObjectName('formLabel')
        layout.addWidget(view_label)

        view_desc = QLabel(
            'Comma-separated view count thresholds.\n'
            'You\'ll be notified when a creator\'s total views cross each threshold.'
        )
        view_desc.setObjectName('countLabel')
        view_desc.setWordWrap(True)
        layout.addWidget(view_desc)

        saved_thresholds = db.get_setting('notification_view_thresholds') or '10000,100000,1000000'
        self._thresholds_edit = QLineEdit(saved_thresholds)
        self._thresholds_edit.setPlaceholderText('e.g. 10000,100000,1000000')
        layout.addWidget(self._thresholds_edit)

        layout.addSpacing(16)

        # Subscriber milestones (informational)
        sub_label = QLabel('Subscriber Milestones:')
        sub_label.setObjectName('formLabel')
        layout.addWidget(sub_label)

        milestones = QLabel(
            'You\'ll automatically be notified when a creator reaches:\n'
            '1K · 5K · 10K · 25K · 50K · 75K · 100K · 250K · 500K · 750K · 1M subscribers'
        )
        milestones.setObjectName('countLabel')
        milestones.setWordWrap(True)
        layout.addWidget(milestones)

        layout.addSpacing(16)

        # Reset alerts button
        reset_btn = QPushButton('Reset All Triggered Alerts')
        reset_btn.setToolTip('Clear all previously triggered alerts so they can fire again')
        reset_btn.clicked.connect(self._on_reset_alerts)
        layout.addWidget(reset_btn)

        layout.addStretch(1)

    def _on_reset_alerts(self) -> None:
        self._db.clear_alerts()
        dark_info(self, 'Alerts Reset', 'All triggered alerts have been cleared.')

    def validate(self) -> bool:
        """Check the threshold list without writing. Returns False (with a
        warning) if the thresholds aren't comma-separated positive integers."""
        text = self._thresholds_edit.text().strip()
        if text:
            try:
                values = [int(t.strip()) for t in text.split(',') if t.strip()]
                assert all(v > 0 for v in values)
            except (ValueError, AssertionError):
                dark_warning(self, 'Invalid Thresholds',
                             'Enter comma-separated positive numbers (e.g. 10000,100000,1000000)')
                return False
        return True
    def save(self) -> bool:
        if not self.validate():
            return False
        text = self._thresholds_edit.text().strip()
        # Commit both settings only after validation passes, so a failed
        # save (and any later Cancel) can't leave the toggle persisted while
        # the thresholds were rejected.
        self._db.set_setting('notifications_enabled', '1' if self._enabled_check.isChecked() else '0')
        self._db.set_setting('notification_view_thresholds', text)
        return True


class _DiscoverTab(QWidget):
    """Discover & Recruit settings: sub ceiling, min views/sub, shorts,
    notifications toggle, and cached-search management."""

    def __init__(self, db: DatabaseManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._db = db
        layout = QVBoxLayout(self)

        # ── Recruitment filters ──
        filters_label = QLabel('Recruitment filters')
        filters_label.setObjectName('formLabel')
        layout.addWidget(filters_label)

        form = QFormLayout()
        self._sub_ceiling = QSpinBox()
        self._sub_ceiling.setRange(0, 10_000_000)
        self._sub_ceiling.setValue(int(db.get_setting('discover_sub_ceiling') or 0))
        self._sub_ceiling.setToolTip('0 = no ceiling (consider creators of any size)')
        form.addRow('Sub ceiling (max subs):', self._sub_ceiling)

        self._min_vps = QSpinBox()
        self._min_vps.setRange(0, 10000)
        self._min_vps.setValue(int(db.get_setting('discover_min_views_per_sub') or 10))
        form.addRow('Min views per sub:', self._min_vps)

        self._shorts_combo = QComboBox()
        for sid, slabel in _SHORTS_MODES:
            self._shorts_combo.addItem(slabel, sid)
        saved_shorts = db.get_setting('discover_shorts') or 'ask'
        # Map legacy 'ask' → default to 'always' in settings (the Discover
        # window itself offers the per-search toggle).
        if saved_shorts not in ('always', 'never'):
            saved_shorts = 'always'
        for i in range(self._shorts_combo.count()):
            if self._shorts_combo.itemData(i) == saved_shorts:
                self._shorts_combo.setCurrentIndex(i)
                break
        form.addRow('Shorts in results:', self._shorts_combo)

        self._sort_combo = QComboBox()
        for sid, slabel in _SORTS:
            self._sort_combo.addItem(slabel, sid)
        saved_sort = db.get_setting('discover_default_sort') or 'potential'
        for i in range(self._sort_combo.count()):
            if self._sort_combo.itemData(i) == saved_sort:
                self._sort_combo.setCurrentIndex(i)
                break
        form.addRow('Default sort:', self._sort_combo)
        layout.addLayout(form)

        hints = QLabel(
            'These are the defaults used when Discover opens. The Discover window '
            'lets you override them per search.\n\n'
            'Sub ceiling = only surface creators with this many subscribers or '
            'fewer. Min views/sub = only surface creators whose total views ÷ '
            'subscribers meets this ratio (the “underviewed audience” signal).'
        )
        hints.setObjectName('countLabel')
        hints.setWordWrap(True)
        layout.addWidget(hints)

        layout.addSpacing(16)

        # ── Notifications ──
        notif_label = QLabel('Notifications')
        notif_label.setObjectName('formLabel')
        layout.addWidget(notif_label)
        self._notif_check = QCheckBox('Notify me about Discover activity')
        self._notif_check.setChecked((db.get_setting('discover_notifications') or '1') == '1')
        self._notif_check.setToolTip('When on, future Discover-related alerts are enabled.')
        layout.addWidget(self._notif_check)

        layout.addSpacing(16)

        # ── Cache management ──
        cache_label = QLabel('Cache')
        cache_label.setObjectName('formLabel')
        layout.addWidget(cache_label)
        self._cache_status = QLabel()
        self._cache_status.setObjectName('countLabel')
        self._cache_status.setWordWrap(True)
        layout.addWidget(self._cache_status)
        self._refresh_cache_status()

        clear_btn = QPushButton('Clear cached searches')
        clear_btn.setToolTip('Delete cached Discover search results (flagged candidates are kept)')
        clear_btn.clicked.connect(self._on_clear_cache)
        layout.addWidget(clear_btn)

        layout.addStretch(1)

    def _refresh_cache_status(self) -> None:
        n = self._db.count_cached_searches()
        self._cache_status.setText(
            f'{n} cached search{"es" if n != 1 else ""}. Cached searches make '
            f're-running the same query free (0 quota units). Flagged '
            f'candidates survive a cache clear.'
        )

    def _on_clear_cache(self) -> None:
        deleted = self._db.clear_discover_cache()
        dark_info(self, 'Cache Cleared', f'Deleted {deleted} cached search(es). Flagged candidates were kept.')
        self._refresh_cache_status()

    def save(self) -> None:
        self._db.set_setting('discover_sub_ceiling', str(self._sub_ceiling.value()))
        self._db.set_setting('discover_min_views_per_sub', str(self._min_vps.value()))
        self._db.set_setting('discover_shorts', self._shorts_combo.currentData())
        self._db.set_setting('discover_default_sort', self._sort_combo.currentData())
        self._db.set_setting('discover_notifications', '1' if self._notif_check.isChecked() else '0')


class SettingsDialog(QDialog):
    """Multi-tab settings dialog: API Keys, Profiles, Role Manager."""
    def __init__(self, db: DatabaseManager, parent: QWidget | None=None, cancel_fetch: Any=None) -> None:
        super().__init__(parent)
        self._db = db
        self._cancel_fetch = cancel_fetch
        self.setWindowTitle('Settings')
        self.setMinimumSize(520, 420)
        self.reapply_theme()
        restore_geometry(self, 'SettingsDialog', self._db)
        self.finished.connect(lambda _r: save_geometry(self, 'SettingsDialog', self._db))
        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        self._api_tab = _ApiKeysTab(db)
        self._verify_tab = _VerifyTab(db)
        self._profiles_tab = _ProfilesTab(db, cancel_fetch=self._cancel_fetch)
        self._roles_tab = _RoleManagerTab(db)
        self._appearance_tab = _AppearanceTab(db)
        self._notifications_tab = _NotificationsTab(db)
        self._discover_tab = _DiscoverTab(db)
        self._tabs.addTab(self._api_tab, 'API Keys')
        self._tabs.addTab(self._verify_tab, 'Verify')
        self._tabs.addTab(self._profiles_tab, 'Profiles')
        self._tabs.addTab(self._roles_tab, 'Roles')
        self._tabs.addTab(self._appearance_tab, 'Appearance')
        self._tabs.addTab(self._notifications_tab, 'Notifications')
        self._tabs.addTab(self._discover_tab, 'Discover')
        layout.addWidget(self._tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def reapply_theme(self) -> None:
        """Rebuild the dialog stylesheet from current theme tokens."""
        self.setStyleSheet(
            build_dialog_qss()
            + f'QLineEdit::placeholder {{ color: {C.INPUT_PLACEHOLDER}; }}\n'
            f'QDialogButtonBox {{ background: transparent; }}\n'
        )

    def _on_save(self) -> None:
        # Validate every tab BEFORE any save() writes, so a rejected tab
        # can't leave a partial commit (e.g. API keys persisted while the
        # notifications thresholds were rejected and the dialog stays open).
        if not self._verify_tab.validate():
            self._tabs.setCurrentWidget(self._verify_tab)
            return
        if not self._notifications_tab.validate():
            self._tabs.setCurrentWidget(self._notifications_tab)
            return
        # All validations passed — commit every tab.
        self._api_tab.save()
        self._verify_tab.save()
        self._appearance_tab.save()
        self._discover_tab.save()
        self._notifications_tab.save()
        # Commit a deferred profile switch *after* the other tabs have saved
        # their values to the previous profile, so the new profile is not
        # overwritten with stale data.
        if not self._profiles_tab.save():
            self._tabs.setCurrentWidget(self._profiles_tab)
            return
        # Apply theme change immediately if it changed
        new_theme = self._appearance_tab._theme_combo.currentData()
        if new_theme != theme_manager.current:
            theme_manager.apply(new_theme)
        self.accept()
    @property
    def profile_changed(self) -> bool:
        return self._profiles_tab.profile_changed
    @property
    def roles_changed(self) -> bool:
        return self._roles_tab.changed