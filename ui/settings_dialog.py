from __future__ import annotations
import json
from typing import Any
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QTabWidget, QTextEdit, QVBoxLayout, QWidget
from PyQt6.QtGui import QColor
from core.db_manager import DatabaseManager
from ui.dialog_utils import dark_info, dark_question, dark_warning
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
        raw = db.get_global_setting('api_keys_json') or '{}'
        keys = json.loads(raw) if raw else {}
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
        raw = self._db.get_global_setting('api_keys_json') or '{}'
        try:
            existing = json.loads(raw)
            if not isinstance(existing, dict):
                existing = {}
        except json.JSONDecodeError:
            existing = {}
        # Validate YouTube key: only update if valid; warn but preserve old value if invalid
        if yt_key:
            if not yt_key.startswith('AIza'):
                dark_warning(self, 'Invalid YouTube Key', 'YouTube API keys must start with \'AIza\'.\nThe YouTube key was not saved; your previous key is preserved.')
                yt_key = existing.get('youtube', '')
            elif len(yt_key) != 39:
                dark_warning(self, 'YouTube Key Warning', f'YouTube API keys are typically 39 characters long (got {len(yt_key)}).\nSaving anyway — verify your key works.')
        keys = {'youtube': yt_key, 'twitch_client_id': twitch_cid, 'twitch_client_secret': twitch_secret, 'anthropic': anthropic_key, 'gemini': gemini_key}
        self._db.set_global_setting('api_keys_json', json.dumps(keys))
        self._db.set_setting('fetch_video_limit', str(self._limit_spin.value()))
class _VerifyTab(QWidget):
    """Community description, AI model selection, and keyword verification settings."""
    _MAX_WORDS = 300
    _MODELS = [
        ('Haiku 4.5 (fastest, cheapest)', 'claude-haiku-4-5-20251001'),
        ('Sonnet 4.6 (balanced)', 'claude-sonnet-4-6'),
        ('Opus 4.8 (most thorough)', 'claude-opus-4-8'),
        ('Gemini 2.5 Flash (fast)', 'gemini-2.5-flash'),
        ('Gemini 2.5 Pro (balanced)', 'gemini-2.5-pro'),
        ('Gemini 2.5 Flash Lite (lightweight)', 'gemini-2.5-flash-lite'),
        ('Gemini 3.5 Flash (latest)', 'gemini-3.5-flash'),
    ]
    def __init__(self, db: DatabaseManager, parent: QWidget | None=None) -> None:
        super().__init__(parent)
        self._db = db
        layout = QVBoxLayout(self)
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
        saved_model = db.get_setting('auto_verify_model') or 'claude-haiku-4-5-20251001'
        for i, (label, model_id) in enumerate(_VerifyTab._MODELS):
            self._model_combo.addItem(label, model_id)
            if model_id == saved_model:
                self._model_combo.setCurrentIndex(i)
        layout.addWidget(self._model_combo)
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
    def _update_word_count(self) -> None:
        text = self._desc_edit.toPlainText()
        word_count = len(text.split()) if text.strip() else 0
        over = word_count > _VerifyTab._MAX_WORDS
        self._word_label.setText(f'{word_count} / {_VerifyTab._MAX_WORDS} words')
        self._word_label.setProperty('over', 'true' if over else 'false')
        qss_refresh(self._word_label)
    def save(self) -> bool:
        text = self._desc_edit.toPlainText().strip()
        word_count = len(text.split()) if text else 0
        if word_count > _VerifyTab._MAX_WORDS:
            dark_warning(
                self, 'Too Many Words',
                f'Community description must be {_VerifyTab._MAX_WORDS} words or fewer (got {word_count}).'
            )
            return False
        self._db.set_setting('community_description', text)
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
        self._color_hex = QLineEdit('#4A90D9')
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
        layout.addStretch(1)
    def _refresh_list(self) -> None:
        self._list.clear()
        for role in self._db.get_roles():
            text = f"{role['role_name']}  ● {role['role_color']}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, role['id'])
            self._list.addItem(item)
    def _pick_color(self) -> None:
        current = QColor(self._color_hex.text())
        if not current.isValid():
            current = QColor('#4A90D9')
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
                current = QColor('#4A90D9')
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

    def save(self) -> bool:
        text = self._thresholds_edit.text().strip()
        # Validate: must be comma-separated positive integers
        if text:
            try:
                values = [int(t.strip()) for t in text.split(',') if t.strip()]
                assert all(v > 0 for v in values)
            except (ValueError, AssertionError):
                dark_warning(self, 'Invalid Thresholds',
                             'Enter comma-separated positive numbers (e.g. 10000,100000,1000000)')
                return False
        self._db.set_setting('notification_view_thresholds', text)
        return True


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
        self._tabs.addTab(self._api_tab, 'API Keys')
        self._tabs.addTab(self._verify_tab, 'Verify')
        self._tabs.addTab(self._profiles_tab, 'Profiles')
        self._tabs.addTab(self._roles_tab, 'Roles')
        self._tabs.addTab(self._appearance_tab, 'Appearance')
        self._tabs.addTab(self._notifications_tab, 'Notifications')
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
        self._api_tab.save()
        if not self._verify_tab.save():
            return
        self._appearance_tab.save()
        if not self._notifications_tab.save():
            self._tabs.setCurrentWidget(self._notifications_tab)
            return
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