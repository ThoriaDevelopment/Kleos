from __future__ import annotations
import json
from typing import Any
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QTabWidget, QTextEdit, QVBoxLayout, QWidget
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QTabWidget, QTextEdit, QVBoxLayout, QWidget
from core.db_manager import DatabaseManager
from ui.dialog_utils import dark_info, dark_question, dark_warning
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
        layout.addLayout(form)
        layout.addSpacing(12)
        limit_label = QLabel('Videos per creator:')
        limit_label.setStyleSheet('font-weight: bold;')
        layout.addWidget(limit_label)
        limit_hint = QLabel('Maximum videos to fetch per creator. Set to 0 for all.')
        limit_hint.setStyleSheet('color: rgba(224,224,224,0.4); font-size: 11px;')
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
        note.setStyleSheet('color: rgba(224,224,224,0.4); font-size: 10px;')
        note.setWordWrap(True)
        layout.addWidget(note)
    def save(self) -> None:
        yt_key = self._yt_key.text().strip()
        twitch_cid = self._twitch_cid.text().strip()
        twitch_secret = self._twitch_secret.text().strip()
        anthropic_key = self._anthropic_key.text().strip()
        if yt_key and (not yt_key.startswith('AIza')):
            dark_warning(self, 'Invalid YouTube Key', 'YouTube API keys must start with \'AIza\'.\nThe YouTube key was not saved, but Twitch keys were saved.')
            yt_key = ''
        else:
            if yt_key and len(yt_key)!= 39:
                    dark_warning(self, 'Invalid YouTube Key', f'YouTube API keys are 39 characters long (got {len(yt_key)}).\nThe YouTube key was not saved, but Twitch keys were saved.')
                    yt_key = ''
        keys = {'youtube': yt_key, 'twitch_client_id': twitch_cid, 'twitch_client_secret': twitch_secret, 'anthropic': anthropic_key}
        self._db.set_global_setting('api_keys_json', json.dumps(keys))
        self._db.set_setting('fetch_video_limit', str(self._limit_spin.value()))
class _VerifyTab(QWidget):
    """Community description and Claude model selection for auto-verification."""
    _MAX_WORDS = 300
    _MODELS = [
        ('Haiku 4.5 (fastest, cheapest)', 'claude-haiku-4-5-20251001'),
        ('Sonnet 4.6 (balanced)', 'claude-sonnet-4-6'),
        ('Opus 4.8 (most thorough)', 'claude-opus-4-8'),
    ]
    def __init__(self, db: DatabaseManager, parent: QWidget | None=None) -> None:
        super().__init__(parent)
        self._db = db
        layout = QVBoxLayout(self)
        desc_label = QLabel('Community Description:')
        desc_label.setStyleSheet('font-weight: bold;')
        layout.addWidget(desc_label)
        desc_hint = QLabel(
            f'Describe your community in {_VerifyTab._MAX_WORDS} words or fewer. '
            'Claude will use this to decide which videos to verify.'
        )
        desc_hint.setStyleSheet('color: rgba(224,224,224,0.5); font-size: 11px;')
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
        self._update_word_count()
        layout.addWidget(self._word_label)
        layout.addSpacing(12)
        model_label = QLabel('Claude Model:')
        model_label.setStyleSheet('font-weight: bold;')
        layout.addWidget(model_label)
        self._model_combo = QComboBox()
        saved_model = db.get_setting('auto_verify_model') or 'claude-haiku-4-5-20251001'
        for i, (label, model_id) in enumerate(_VerifyTab._MODELS):
            self._model_combo.addItem(label, model_id)
            if model_id == saved_model:
                self._model_combo.setCurrentIndex(i)
        layout.addWidget(self._model_combo)
        layout.addStretch(1)
    def _update_word_count(self) -> None:
        text = self._desc_edit.toPlainText()
        word_count = len(text.split()) if text.strip() else 0
        color = '#FF6B35' if word_count > _VerifyTab._MAX_WORDS else 'rgba(224,224,224,0.5)'
        self._word_label.setText(f'{word_count} / {_VerifyTab._MAX_WORDS} words')
        self._word_label.setStyleSheet(f'color: {color}; font-size: 11px;')
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
        return True
class _ProfilesTab(QWidget):
    """Create, rename, and switch between database profiles."""
    def __init__(self, db: DatabaseManager, parent: QWidget | None=None, cancel_fetch: Any=None) -> None:
        super().__init__(parent)
        self._db = db
        self._profile_changed = False
        self._cancel_fetch = cancel_fetch
        layout = QVBoxLayout(self)
        h_current = QHBoxLayout()
        h_current.addWidget(QLabel('Active Profile:'))
        self._current_label = QLabel(db.profile)
        self._current_label.setStyleSheet('font-weight: bold; color: #4A90D9; background: transparent;')
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
        delete_btn.setStyleSheet('QPushButton { color: #FF6B35; background: #2E2E2E; border: 1px solid #3A3A3A;   border-radius: 4px; padding: 6px 14px; }QPushButton:hover { background: #4A4A4A; }')
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
        current = self._db.profile
        for name in self._db.list_profiles():
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
                    self._db.switch_profile(name)
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
            if name == self._db.profile:
                return None
            else:
                if self._cancel_fetch:
                    self._cancel_fetch()
                self._db.switch_profile(name)
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
                    from core.paths import STORAGE_DIR
                    for ext in ['', '-wal', '-shm']:
                        p = STORAGE_DIR / f'{name}.db{ext}'
                        try:
                            p.unlink(missing_ok=True)
                        except OSError:
                            pass
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
        del_btn.setStyleSheet('QPushButton { color: #FF6B35; background: #2E2E2E; border: 1px solid #3A3A3A;   border-radius: 4px; padding: 6px 14px; }QPushButton:hover { background: #4A4A4A; }')
        del_btn.clicked.connect(self._on_delete)
        layout.addWidget(del_btn)
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
    @property
    def changed(self) -> bool:
        return self._changed
class _AppearanceTab(QWidget):
    """Appearance settings: thumbnail quality toggle."""
    def __init__(self, db: DatabaseManager, parent: QWidget | None=None) -> None:
        super().__init__(parent)
        self._db = db
        layout = QVBoxLayout(self)
        thumb_label = QLabel('Thumbnail Quality:')
        thumb_label.setStyleSheet('font-weight: bold;')
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
        thumb_hint.setStyleSheet('color: rgba(224,224,224,0.4); font-size: 11px;')
        thumb_hint.setWordWrap(True)
        layout.addWidget(thumb_hint)
        layout.addStretch(1)
    def save(self) -> None:
        self._db.set_setting('thumbnail_quality', self._thumb_combo.currentData())
class SettingsDialog(QDialog):
    """Multi-tab settings dialog: API Keys, Profiles, Role Manager."""
    def __init__(self, db: DatabaseManager, parent: QWidget | None=None, cancel_fetch: Any=None) -> None:
        super().__init__(parent)
        self._db = db
        self._cancel_fetch = cancel_fetch
        self.setWindowTitle('Settings')
        self.setMinimumSize(520, 420)
        self.setStyleSheet('QDialog { background: #1A1A1A; }QLabel { color: #E0E0E0; }QTabWidget::pane { border: 1px solid #3A3A3A; background: #222222; }QTabBar::tab { background: #222222; color: #aaa; padding: 8px 20px;   border: 1px solid #3A3A3A; border-bottom: none; border-radius: 4px 4px 0 0; }QTabBar::tab:selected { background: #2E2E2E; color: #E0E0E0; }QLineEdit { background: #222222; color: #E0E0E0; border: 1px solid #3A3A3A;   border-radius: 4px; padding: 4px 8px; }QLineEdit::placeholder { color: rgba(224,224,224,0.4); }QTextEdit { background: #222222; color: #E0E0E0; border: 1px solid #3A3A3A;   border-radius: 4px; padding: 4px 8px; }QComboBox { background: #222222; color: #E0E0E0; border: 1px solid #3A3A3A;   border-radius: 4px; padding: 4px 8px; }QComboBox QAbstractItemView { background: #1C1C22; color: #E0E0E0; border: 1px solid #3A3A3A; selection-background-color: #2A2A33; }QListWidget { background: #222222; color: #E0E0E0; border: 1px solid #3A3A3A;   border-radius: 4px; }QListWidget::item:selected { background: #3A3A3A; }QPushButton { background: #2E2E2E; color: #E0E0E0; border: 1px solid #3A3A3A;   border-radius: 4px; padding: 6px 14px; }QPushButton:hover { background: #4A4A4A; }QDialogButtonBox { background: transparent; }')
        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        self._api_tab = _ApiKeysTab(db)
        self._verify_tab = _VerifyTab(db)
        self._profiles_tab = _ProfilesTab(db, cancel_fetch=self._cancel_fetch)
        self._roles_tab = _RoleManagerTab(db)
        self._appearance_tab = _AppearanceTab(db)
        self._tabs.addTab(self._api_tab, 'API Keys')
        self._tabs.addTab(self._verify_tab, 'Verify')
        self._tabs.addTab(self._profiles_tab, 'Profiles')
        self._tabs.addTab(self._roles_tab, 'Roles')
        self._tabs.addTab(self._appearance_tab, 'Appearance')
        layout.addWidget(self._tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    def _on_save(self) -> None:
        self._api_tab.save()
        if not self._verify_tab.save():
            return
        self._appearance_tab.save()
        self.accept()
    @property
    def profile_changed(self) -> bool:
        return self._profiles_tab.profile_changed
    @property
    def roles_changed(self) -> bool:
        return self._roles_tab.changed