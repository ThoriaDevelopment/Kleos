from __future__ import annotations
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .paths import BACKUPS_DIR, GLOBAL_SETTINGS_PATH, STORAGE_DIR

logger = logging.getLogger(__name__)
MAX_BACKUPS = 3
_BACKUP_DEBOUNCE_S = 60.0
_PROFILE_RE = re.compile(r'^[A-Za-z0-9 _-]+$')


def _validate_profile_name(name: str) -> None:
    """Raise ValueError if *name* contains path separators or unsafe chars."""
    if not name or not _PROFILE_RE.match(name):
        raise ValueError(
            f'Invalid profile name: {name!r}. '
            'Use only letters, numbers, spaces, hyphens, and underscores.'
        )

_GLOBAL_LOCK = threading.Lock()
_GLOBAL_DEFAULTS: dict[str, str] = {'last_profile': 'default', 'api_keys_json': '{}', 'first_run_complete': ''}


def _read_global_settings() -> dict[str, str]:
    """Read global_settings.json, returning defaults if the file is missing."""
    if GLOBAL_SETTINGS_PATH.exists():
        try:
            with open(GLOBAL_SETTINGS_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {**_GLOBAL_DEFAULTS, **data}
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_GLOBAL_DEFAULTS)


def _write_global_settings(settings: dict[str, str]) -> None:
    """Write global_settings.json atomically via temp file + os.replace."""
    GLOBAL_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(GLOBAL_SETTINGS_PATH.parent), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(GLOBAL_SETTINGS_PATH))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
_SCHEMA = '\nCREATE TABLE IF NOT EXISTS settings (\n    key     TEXT PRIMARY KEY,\n    value   TEXT NOT NULL\n);\n\nCREATE TABLE IF NOT EXISTS roles (\n    id          INTEGER PRIMARY KEY AUTOINCREMENT,\n    role_name   TEXT    NOT NULL UNIQUE,\n    role_color  TEXT    NOT NULL\n);\n\nCREATE TABLE IF NOT EXISTS creators (\n    id            INTEGER PRIMARY KEY AUTOINCREMENT,\n    nickname      TEXT    NOT NULL,\n    platforms     TEXT    NOT NULL DEFAULT \'[]\',\n    role_id       INTEGER NOT NULL,\n    youtube_type  TEXT,\n    youtube_channel_id TEXT,\n    youtube_link  TEXT,\n    twitch_link   TEXT,\n    pfp_url       TEXT,\n    date_added       TEXT    NOT NULL DEFAULT (strftime(\'%Y-%m-%dT%H:%M:%SZ\', \'now\')),\n    is_new_activity  INTEGER NOT NULL DEFAULT 0,\n    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE RESTRICT\n);\n\nCREATE TABLE IF NOT EXISTS media_content (\n    id              INTEGER PRIMARY KEY AUTOINCREMENT,\n    creator_id      INTEGER NOT NULL,\n    platform        TEXT    NOT NULL CHECK(platform IN (\'youtube\', \'twitch\')),\n    content_id      TEXT    NOT NULL UNIQUE,\n    title           TEXT    NOT NULL DEFAULT \'\',\n    thumbnail_path  TEXT    NOT NULL DEFAULT \'\',\n    thumbnail_url   TEXT    NOT NULL DEFAULT \'\',\n    upload_date     TEXT    NOT NULL DEFAULT \'\',\n    view_count      INTEGER NOT NULL DEFAULT 0,\n    is_verified     INTEGER NOT NULL DEFAULT 0,\n    is_short        INTEGER NOT NULL DEFAULT 0,\n    is_stream       INTEGER NOT NULL DEFAULT 0,\n    type_override   TEXT    DEFAULT NULL,\n    description     TEXT    NOT NULL DEFAULT \'\',\n    FOREIGN KEY (creator_id) REFERENCES creators(id) ON DELETE CASCADE\n);\n\nCREATE INDEX IF NOT EXISTS idx_media_creator  ON media_content(creator_id);\nCREATE INDEX IF NOT EXISTS idx_media_platform  ON media_content(platform);\nCREATE INDEX IF NOT EXISTS idx_content_id      ON media_content(content_id);\n'
_SCHEMA_VERSION = 6  # Increment when adding new migrations

# Migrate old invalid Anthropic model IDs to valid API identifiers.
_MODEL_ID_MIGRATION = {
    'claude-haiku-4-5': 'claude-haiku-4-5-20251001',
}

_DEFAULT_SETTINGS = {'community_description': '', 'auto_verify_model': 'claude-haiku-4-5-20251001', 'fetch_video_limit': '50', 'thumbnail_quality': 'low', 'notification_view_thresholds': '10000,100000,1000000'}
class DatabaseManager:
    """Thread-safe SQLite manager with profile switching and auto-backup.

    Uses two separate SQLite connections:
    - ``_conn`` (write connection): serialised via ``_write_lock``.
    - ``_read_conn`` (read connection): serialised via ``_read_lock``.
    Because WAL mode allows concurrent reads while a write is in progress,
    reads on ``_read_conn`` never block on writes and vice-versa.
    """

    def __init__(self, profile: str='default') -> None:
        self._write_lock = threading.Lock()
        self._read_lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._read_conn: sqlite3.Connection | None = None
        self._profile = ''
        self._last_backup_time = 0.0
        self._last_fetch_time = 0.0
        self.switch_profile(profile)
        self._migrate_api_keys_to_global()
    @staticmethod
    def _connect(db_path: Path) -> sqlite3.Connection:
        """Open a single SQLite connection with WAL mode and foreign keys enabled."""
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA foreign_keys=ON')
        return conn
    def _init_schema(self, conn: sqlite3.Connection) -> None:
        """Create tables and apply schema migrations atomically.

        Uses PRAGMA user_version to track which migrations have been applied.
        Column-existence ALTER TABLE guards are retained as a safety net for
        databases created before version tracking was introduced.
        """
        conn.executescript(_SCHEMA)

        # Insert default settings that don't yet exist.
        for key, value in _DEFAULT_SETTINGS.items():
            conn.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))
        conn.commit()

        # Apply versioned migrations.  Each migration runs inside an
        # explicit transaction; if it fails, the transaction is rolled
        # back and further migrations are skipped.
        current_version = conn.execute('PRAGMA user_version').fetchone()[0]
        if current_version < _SCHEMA_VERSION:
            for target_version in range(current_version + 1, _SCHEMA_VERSION + 1):
                try:
                    conn.execute('BEGIN')
                    self._apply_migration(conn, target_version)
                    conn.execute(f'PRAGMA user_version = {target_version}')
                    conn.execute('COMMIT')
                except sqlite3.Error as exc:
                    conn.execute('ROLLBACK')
                    logger.warning('Schema migration to v%d failed: %s', target_version, exc)
                    break

        # Column-existence guards: these are idempotent safety nets for
        # databases created before PRAGMA user_version was introduced.
        cols = [row['name'] for row in conn.execute('PRAGMA table_info(creators)')]
        if 'youtube_type' not in cols:
            conn.execute('ALTER TABLE creators ADD COLUMN youtube_type TEXT')
        if 'is_new_activity' not in cols:
            conn.execute('ALTER TABLE creators ADD COLUMN is_new_activity INTEGER NOT NULL DEFAULT 0')
        if 'youtube_channel_id' not in cols:
            conn.execute('ALTER TABLE creators ADD COLUMN youtube_channel_id TEXT')
        if 'youtube_link' not in cols:
            conn.execute('ALTER TABLE creators ADD COLUMN youtube_link TEXT')
        if 'pfp_url' not in cols:
            conn.execute('ALTER TABLE creators ADD COLUMN pfp_url TEXT')
        if 'twitch_link' not in cols:
            conn.execute('ALTER TABLE creators ADD COLUMN twitch_link TEXT')
        if 'notes' not in cols:
            conn.execute("ALTER TABLE creators ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
        if 'tags' not in cols:
            conn.execute("ALTER TABLE creators ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")
        media_cols = [row['name'] for row in conn.execute('PRAGMA table_info(media_content)')]
        if 'is_short' not in media_cols:
            conn.execute('ALTER TABLE media_content ADD COLUMN is_short INTEGER NOT NULL DEFAULT 0')
        if 'thumbnail_url' not in media_cols:
            conn.execute('ALTER TABLE media_content ADD COLUMN thumbnail_url TEXT NOT NULL DEFAULT \'\'')
        if 'description' not in media_cols:
            conn.execute('ALTER TABLE media_content ADD COLUMN description TEXT NOT NULL DEFAULT \'\'')
        if 'is_stream' not in media_cols:
            conn.execute('ALTER TABLE media_content ADD COLUMN is_stream INTEGER NOT NULL DEFAULT 0')
        if 'type_override' not in media_cols:
            conn.execute('ALTER TABLE media_content ADD COLUMN type_override TEXT DEFAULT NULL')
        conn.commit()

    @staticmethod
    def _apply_migration(conn: sqlite3.Connection, version: int) -> None:
        """Apply a single schema migration for the given *version*.

        Each version maps to a set of SQL statements that are executed
        inside an explicit transaction by the caller.
        """
        if version == 2:
            # v1→v2: migrate old invalid Anthropic model IDs to valid ones.
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'auto_verify_model'"
            ).fetchone()
            if row and row['value'] in _MODEL_ID_MIGRATION:
                conn.execute(
                    "UPDATE settings SET value = ? WHERE key = 'auto_verify_model'",
                    (_MODEL_ID_MIGRATION[row['value']],),
                )
        if version == 3:
            # v2→v3: add notes column to creators table.
            cols = [row['name'] for row in conn.execute('PRAGMA table_info(creators)')]
            if 'notes' not in cols:
                conn.execute("ALTER TABLE creators ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
        if version == 4:
            # v3→v4: add tags column to creators and alerts table for notifications.
            cols = [row['name'] for row in conn.execute('PRAGMA table_info(creators)')]
            if 'tags' not in cols:
                conn.execute("ALTER TABLE creators ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")
            conn.execute(
                'CREATE TABLE IF NOT EXISTS alerts ('
                'id INTEGER PRIMARY KEY AUTOINCREMENT, '
                'creator_id INTEGER NOT NULL, '
                'alert_type TEXT NOT NULL CHECK(alert_type IN (\'view_milestone\', \'subscriber_milestone\')), '
                'threshold INTEGER NOT NULL, '
                'triggered_at TEXT NOT NULL DEFAULT \'\', '
                'FOREIGN KEY (creator_id) REFERENCES creators(id) ON DELETE CASCADE)'
            )
            conn.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_unique '
                'ON alerts(creator_id, alert_type, threshold)'
            )
        if version == 5:
            # v4→v5: add is_stream column to media_content.
            media_cols = [row['name'] for row in conn.execute('PRAGMA table_info(media_content)')]
            if 'is_stream' not in media_cols:
                conn.execute('ALTER TABLE media_content ADD COLUMN is_stream INTEGER NOT NULL DEFAULT 0')
        if version == 6:
            # v5→v6: add type_override column for manual content-type overrides.
            media_cols = [row['name'] for row in conn.execute('PRAGMA table_info(media_content)')]
            if 'type_override' not in media_cols:
                conn.execute('ALTER TABLE media_content ADD COLUMN type_override TEXT DEFAULT NULL')
    @property
    def profile(self) -> str:
        return self._profile
    @property
    def current_profile(self) -> str:
        """Snapshot of the active profile name for abort-checking by workers."""
        with self._write_lock:
            return self._profile
    @property
    def last_fetch_time(self) -> float:
        return self._last_fetch_time
    @last_fetch_time.setter
    def last_fetch_time(self, value: float) -> None:
        self._last_fetch_time = value
    def switch_profile(self, profile: str) -> None:
        """Switch to *profile*, creating the database if it doesn't exist.

        If initialisation fails the old connection is preserved so the
        manager remains usable.
        """
        _validate_profile_name(profile)
        with self._write_lock:
            old_conn = self._conn
            old_read_conn = self._read_conn
            old_profile = self._profile
            STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
            db_path = STORAGE_DIR / f'{profile}.db'
            try:
                new_conn = self._connect(db_path)
                new_read_conn = self._connect(db_path)
                self._init_schema(new_conn)
                new_conn.commit()
                # Only swap after everything succeeded.
                self._conn = new_conn
                self._read_conn = new_read_conn
                self._profile = profile
                # Persist the active profile name in global settings so the
                # next launch opens the same profile the user was using.
                with _GLOBAL_LOCK:
                    settings = _read_global_settings()
                    settings['last_profile'] = profile
                    _write_global_settings(settings)
                if old_conn is not None:
                    try:
                        old_conn.close()
                    except Exception:
                        pass
                if old_read_conn is not None:
                    try:
                        old_read_conn.close()
                    except Exception:
                        pass
            except Exception:
                # New connection failed — discard it but keep old_conn alive.
                try:
                    if 'new_conn' in locals() and new_conn is not None:
                        new_conn.close()
                except Exception:
                    pass
                try:
                    if 'new_read_conn' in locals() and new_read_conn is not None:
                        new_read_conn.close()
                except Exception:
                    pass
                raise
    def list_profiles(self) -> list[str]:
        """Return all profile names found in the storage directory."""
        return sorted((p.stem for p in STORAGE_DIR.glob('*.db')))

    def delete_profile(self, profile: str) -> None:
        """Delete a profile database and its associated files.

        Raises ValueError if *profile* is the currently active profile or
        contains unsafe characters.
        """
        _validate_profile_name(profile)
        if profile == self._profile:
            raise ValueError('Cannot delete the active profile. Switch to another profile first.')
        for ext in ('', '-wal', '-shm'):
            path = STORAGE_DIR / f'{profile}.db{ext}'
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning('Failed to delete %s: %s', path, exc)

    def get_all_thumbnail_paths(self) -> list[str]:
        """Return all non-empty thumbnail_path values from media_content."""
        return [
            row['thumbnail_path']
            for row in self._read("SELECT thumbnail_path FROM media_content WHERE thumbnail_path != ''")
            if row['thumbnail_path']
        ]
    def _backup(self) -> None:
        """Create a timestamped backup and prune to MAX_BACKUPS.

        Checkpoints the WAL inside the write lock first so the .db file
        contains all committed data, then offloads the file copy to a
        background thread so reads aren't blocked.

        Note: the file copy happens outside the lock, so new writes between
        the checkpoint and the copy are not captured.  This is acceptable
        for a best-effort point-in-time backup — the backup reflects all
        data committed before the checkpoint.
        """
        with self._write_lock:
            now = time.monotonic()
            if now - self._last_backup_time < _BACKUP_DEBOUNCE_S:
                return
            else:
                self._last_backup_time = now
                if self._conn is not None:
                    try:
                        self._conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                        self._conn.commit()
                    except sqlite3.Error:
                        pass
                profile_snapshot = self._profile
        ts = f'{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")}_{int(time.monotonic() * 1000000) % 1000000:06d}Z'
        src = STORAGE_DIR / f'{profile_snapshot}.db'
        dst = BACKUPS_DIR / f'{profile_snapshot}_{ts}.db.bak'
        def _do_copy():
            try:
                shutil.copy2(str(src), str(dst))
                backups = sorted(BACKUPS_DIR.glob(f'{profile_snapshot}_*.db.bak'))
                for old in backups[:-MAX_BACKUPS]:
                    old.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning('Backup copy failed: %s', exc)
        threading.Thread(target=_do_copy, daemon=True).start()
    def _write(self, sql: str, params: tuple=()) -> sqlite3.Cursor:
        """Execute a write statement with error handling.

        Returns the cursor on success.  Raises ``ValueError`` with a
        human-readable message on database errors instead of propagating
        raw ``sqlite3`` exceptions.
        """
        if self._conn is None:
            raise RuntimeError('DatabaseManager is closed')
        with self._write_lock:
            try:
                cursor = self._conn.execute(sql, params)
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
                raise ValueError(f'Database constraint violation: {exc}') from exc
            except sqlite3.Error as exc:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
                raise ValueError(f'Database error: {exc}') from exc
        self._backup()
        return cursor

    def _read(self, sql: str, params: tuple=()) -> list[dict[str, Any]]:
        """Execute a read query on the read connection and return rows as dicts.

        Uses a separate connection so reads never block on writes (WAL mode).
        """
        if self._read_conn is None:
            raise RuntimeError('DatabaseManager is closed')
        with self._read_lock:
            cursor = self._read_conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
    def bulk_last_activity(self) -> dict[int, str]:
        """Return {creator_id: last_upload_date} for all creators."""
        rows = self._read('SELECT creator_id, MAX(upload_date) AS last_activity FROM media_content GROUP BY creator_id')
        return {r['creator_id']: r['last_activity'] for r in rows}
    def bulk_unverified_creators(self) -> set[int]:
        """Return set of creator IDs that have at least one unverified item."""
        rows = self._read('SELECT DISTINCT creator_id FROM media_content WHERE is_verified = 0')
        return {r['creator_id'] for r in rows}
    def bulk_new_activity_creators(self) -> set[int]:
        """Return set of creator IDs flagged with new-activity alert."""
        rows = self._read('SELECT id FROM creators WHERE is_new_activity = 1')
        return {r['id'] for r in rows}

    def bulk_subscriber_counts(self) -> dict[int, dict[str, int]]:
        """Return {creator_id: {'youtube': subs, 'twitch': followers}} for all creators.

        Values are 0 when no data has been fetched yet.
        """
        creators = self.get_creators()
        result: dict[int, dict[str, int]] = {c['id']: {} for c in creators}

        # Fetch all subscriber/follower settings in two bulk queries
        # instead of N+1 individual get_setting() calls.
        yt_rows = self._read(
            "SELECT key, value FROM settings WHERE key LIKE 'yt_channel_subscribers_%'"
        )
        tw_rows = self._read(
            "SELECT key, value FROM settings WHERE key LIKE 'twitch_followers_%'"
        )

        for row in yt_rows:
            try:
                cid = int(row['key'].rsplit('_', 1)[-1])
            except (ValueError, IndexError):
                continue
            if cid in result:
                raw = row['value']
                result[cid]['youtube'] = int(raw) if raw and raw.isdigit() else 0

        for row in tw_rows:
            try:
                cid = int(row['key'].rsplit('_', 1)[-1])
            except (ValueError, IndexError):
                continue
            if cid in result:
                raw = row['value']
                result[cid]['twitch'] = int(raw) if raw and raw.isdigit() else 0

        # Fill in platform membership and defaults for creators with no data.
        for c in creators:
            platforms = json.loads(c.get('platforms', '[]'))
            if 'youtube' in platforms and 'youtube' not in result[c['id']]:
                result[c['id']]['youtube'] = 0
            if 'twitch' in platforms and 'twitch' not in result[c['id']]:
                result[c['id']]['twitch'] = 0

        return result
    def clear_new_activity(self, creator_id: int) -> None:
        """Clear the new-activity alert flag for a creator (on inspection)."""
        self._write('UPDATE creators SET is_new_activity = 0 WHERE id = ?', (creator_id,))
    def ingest_channel_payloads(self, creator_id: int, payloads: dict[str, dict[str, Any]]) -> None:
        """Write multi-platform metadata into the creator record.\n\nExpected *payloads* shape:\n    {\n        \"youtube\": {\"display_name\": str, \"views\": int, \"pfp_url\": str},\n        \"twitch\":  {\"display_name\": str, \"followers\": int, \"pfp_url\": str},\n    }\n"""
        kwargs = {}
        yt = payloads.get('youtube')
        if yt:
            if yt.get('display_name'):
                kwargs['nickname'] = yt['display_name']
            if yt.get('pfp_url'):
                kwargs['pfp_url'] = yt['pfp_url']
            if yt.get('views') is not None:
                self.set_setting(f"yt_channel_views_{creator_id}", str(yt['views']))
        tw = payloads.get('twitch')
        if tw:
            if tw.get('display_name') and 'nickname' not in kwargs:
                kwargs['nickname'] = tw['display_name']
            if tw.get('pfp_url') and 'pfp_url' not in kwargs:
                kwargs['pfp_url'] = tw['pfp_url']
            if tw.get('followers') is not None:
                self.set_setting(f"twitch_followers_{creator_id}", str(tw['followers']))
        if kwargs:
            self.update_creator(creator_id, **kwargs)
    def ingest_youtube_channel_payload(self, creator_id: int, payload: dict[str, Any]) -> None:
        """Legacy wrapper that routes a single YouTube payload through the\nunified multi-platform ingestor.\n"""
        self.ingest_channel_payloads(creator_id, {'youtube': payload})
    def set_new_activity(self, creator_id: int) -> None:
        """Set the new-activity alert flag for a creator (on new content)."""
        self._write('UPDATE creators SET is_new_activity = 1 WHERE id = ?', (creator_id,))
    def get_setting(self, key: str) -> str | None:
        rows = self._read('SELECT value FROM settings WHERE key = ?', (key,))
        if rows:
            return rows[0]['value']
    def set_setting(self, key: str, value: str) -> None:
        self._write('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value', (key, value))

    def get_global_setting(self, key: str) -> str | None:
        """Read a setting from the global JSON file (shared across all profiles)."""
        with _GLOBAL_LOCK:
            settings = _read_global_settings()
        return settings.get(key)

    def set_global_setting(self, key: str, value: str) -> None:
        """Write a setting to the global JSON file (shared across all profiles)."""
        with _GLOBAL_LOCK:
            settings = _read_global_settings()
            settings[key] = value
            _write_global_settings(settings)

    def _migrate_api_keys_to_global(self) -> None:
        """One-time migration: copy api_keys_json from the per-profile DB
        to the global settings file, if the global file doesn't exist yet."""
        with _GLOBAL_LOCK:
            if GLOBAL_SETTINGS_PATH.exists():
                return  # Already migrated
            raw = self.get_setting('api_keys_json') or '{}'
            settings = _read_global_settings()
            settings['api_keys_json'] = raw
            _write_global_settings(settings)
    def add_role(self, role_name: str, role_color: str) -> int:
        cur = self._write('INSERT INTO roles (role_name, role_color) VALUES (?, ?)', (role_name, role_color))
        return cur.lastrowid
    def get_roles(self) -> list[dict[str, Any]]:
        return self._read('SELECT * FROM roles ORDER BY id')
    def get_role(self, role_id: int) -> dict[str, Any] | None:
        rows = self._read('SELECT * FROM roles WHERE id = ?', (role_id,))
        if rows:
            return rows[0]
    def update_role(self, role_id: int, role_name: str | None=None, role_color: str | None=None) -> None:
        parts = []
        vals = []
        if role_name is not None:
            parts.append('role_name = ?')
            vals.append(role_name)
        if role_color is not None:
            parts.append('role_color = ?')
            vals.append(role_color)
        if not parts:
            return None
        else:
            vals.append(role_id)
            self._write(f"UPDATE roles SET {', '.join(parts)} WHERE id = ?", tuple(vals))
    def delete_role(self, role_id: int) -> None:
        """Delete a role. Raises ``ValueError`` if the role is in use."""
        in_use = self._read('SELECT 1 FROM creators WHERE role_id = ? LIMIT 1', (role_id,))
        if in_use:
            raise ValueError(f'Role {role_id} is assigned to creators and cannot be deleted.')
        else:
            self._write('DELETE FROM roles WHERE id = ?', (role_id,))
    def add_creator(self, nickname: str, role_id: int, platforms: list[str] | None=None, youtube_channel_id: str | None=None, youtube_link: str | None=None, twitch_link: str | None=None, pfp_url: str | None=None, notes: str | None=None, tags: list[str] | None=None) -> int:
        platforms_json = json.dumps(platforms or [])
        notes_val = notes or ''
        tags_json = json.dumps(tags) if tags is not None else '[]'
        cur = self._write('INSERT INTO creators (nickname, platforms, role_id, youtube_channel_id, youtube_link, twitch_link, pfp_url, notes, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (nickname, platforms_json, role_id, youtube_channel_id, youtube_link, twitch_link, pfp_url, notes_val, tags_json))
        return cur.lastrowid
    def get_creators(self) -> list[dict[str, Any]]:
        return self._read('SELECT * FROM creators ORDER BY id')
    def get_creator(self, creator_id: int) -> dict[str, Any] | None:
        rows = self._read('SELECT * FROM creators WHERE id = ?', (creator_id,))
        if rows:
            return rows[0]
    def update_creator(self, creator_id: int, nickname: str | None=None, platforms: list[str] | None=None, role_id: int | None=None, youtube_channel_id: str | None=None, youtube_link: str | None=None, twitch_link: str | None=None, pfp_url: str | None=None, date_added: str | None=None, notes: str | None=None, tags: list[str] | None=None) -> None:
        parts = []
        vals = []
        if nickname is not None:
            parts.append('nickname = ?')
            vals.append(nickname)
        if platforms is not None:
            parts.append('platforms = ?')
            vals.append(json.dumps(platforms))
        if role_id is not None:
            parts.append('role_id = ?')
            vals.append(role_id)
        if youtube_channel_id is not None:
            parts.append('youtube_channel_id = ?')
            vals.append(youtube_channel_id)
        if youtube_link is not None:
            parts.append('youtube_link = ?')
            vals.append(youtube_link)
        if twitch_link is not None:
            parts.append('twitch_link = ?')
            vals.append(twitch_link)
        if pfp_url is not None:
            parts.append('pfp_url = ?')
            vals.append(pfp_url)
        if date_added is not None:
            parts.append('date_added = ?')
            vals.append(date_added)
        if notes is not None:
            parts.append('notes = ?')
            vals.append(notes)
        if tags is not None:
            parts.append('tags = ?')
            vals.append(json.dumps(tags))
        if not parts:
            return None
        else:
            vals.append(creator_id)
            self._write(f"UPDATE creators SET {', '.join(parts)} WHERE id = ?", tuple(vals))
    def delete_creator(self, creator_id: int) -> None:
        self._write('DELETE FROM creators WHERE id = ?', (creator_id,))
        for prefix in ('yt_channel_subscribers_', 'yt_channel_views_', 'twitch_followers_'):
            self._write('DELETE FROM settings WHERE key = ?', (f'{prefix}{creator_id}',))
    def add_media(self, creator_id: int, platform: str, content_id: str, title: str='', thumbnail_path: str='', upload_date: str='', view_count: int=0, is_verified: bool=False, is_short: bool=False, is_stream: bool=False, thumbnail_url: str='', description: str='') -> int:
        cur = self._write('INSERT INTO media_content (creator_id, platform, content_id, title, thumbnail_path, thumbnail_url, upload_date, view_count, is_verified, is_short, is_stream, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (creator_id, platform, content_id, title, thumbnail_path, thumbnail_url, upload_date, view_count, int(is_verified), int(is_short), int(is_stream), description))
        return cur.lastrowid
    def get_media(self, creator_id: int | None=None, platform: str | None=None) -> list[dict[str, Any]]:
        parts = []
        vals = []
        if creator_id is not None:
            parts.append('creator_id = ?')
            vals.append(creator_id)
        if platform is not None:
            parts.append('platform = ?')
            vals.append(platform)
        where = f"WHERE {' AND '.join(parts)}" if parts else ''
        return self._read(f'SELECT * FROM media_content {where} ORDER BY upload_date DESC', tuple(vals))
    def get_media_by_content_id(self, content_id: str) -> dict[str, Any] | None:
        rows = self._read('SELECT * FROM media_content WHERE content_id = ?', (content_id,))
        if rows:
            return rows[0]
    def upsert_media(self, creator_id: int, platform: str, content_id: str, title: str='', thumbnail_path: str='', upload_date: str='', view_count: int=0, is_short: bool=False, is_stream: bool=False, thumbnail_url: str='', description: str='') -> None:
        """Insert or update a media record, **preserving** existing is_verified and type_override.

        When the content_id is new (INSERT, not UPDATE), the creator's
        ``is_new_activity`` flag is set to 1 so the dashboard alert shows.

        If a user has manually overridden the content type (type_override is
        not NULL), the is_short and is_stream columns are preserved rather
        than overwritten by the API-derived values.

        The existence check and write are done in a single lock scope to
        avoid a TOCTOU race with concurrent upserts.
        """
        is_new = False
        with self._write_lock:
            existing = self._conn.execute(
                'SELECT 1 FROM media_content WHERE content_id = ?', (content_id,)
            ).fetchone()
            self._conn.execute(
                'INSERT INTO media_content (creator_id, platform, content_id, title, thumbnail_path, thumbnail_url, upload_date, view_count, is_verified, is_short, is_stream, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?) ON CONFLICT(content_id) DO UPDATE SET title = excluded.title, thumbnail_path = excluded.thumbnail_path, thumbnail_url = excluded.thumbnail_url, upload_date = excluded.upload_date, view_count = excluded.view_count, is_short = CASE WHEN media_content.type_override IS NOT NULL THEN media_content.is_short ELSE excluded.is_short END, is_stream = CASE WHEN media_content.type_override IS NOT NULL THEN media_content.is_stream ELSE excluded.is_stream END, description = excluded.description',
                (creator_id, platform, content_id, title, thumbnail_path, thumbnail_url, upload_date, view_count, int(is_short), int(is_stream), description)
            )
            if not existing:
                is_new = True
                self._conn.execute('UPDATE creators SET is_new_activity = 1 WHERE id = ?', (creator_id,))
            self._conn.commit()
        if is_new:
            self._backup()

    def upsert_media_batch(self, records: list[dict[str, Any]]) -> None:
        """Batch-insert or update multiple media records in a single transaction.

        Each record dict should have the same keys as ``upsert_media`` parameters:
        creator_id, platform, content_id, title, thumbnail_path, thumbnail_url,
        upload_date, view_count, is_short, description.

        Preserves existing ``is_verified`` and ``type_override`` on conflict.
        When a user has manually overridden the content type, ``is_short`` and
        ``is_stream`` are preserved rather than overwritten by API values.
        Sets the creator's ``is_new_activity`` flag only for genuinely new content_ids.
        """
        if not records:
            return
        new_creator_ids = set()
        with self._write_lock:
            try:
                for rec in records:
                    existing = self._conn.execute(
                        'SELECT 1 FROM media_content WHERE content_id = ?', (rec['content_id'],)
                    ).fetchone()
                    self._conn.execute(
                        'INSERT INTO media_content (creator_id, platform, content_id, title, thumbnail_path, thumbnail_url, upload_date, view_count, is_verified, is_short, is_stream, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?) ON CONFLICT(content_id) DO UPDATE SET title = excluded.title, thumbnail_path = excluded.thumbnail_path, thumbnail_url = excluded.thumbnail_url, upload_date = excluded.upload_date, view_count = excluded.view_count, is_short = CASE WHEN media_content.type_override IS NOT NULL THEN media_content.is_short ELSE excluded.is_short END, is_stream = CASE WHEN media_content.type_override IS NOT NULL THEN media_content.is_stream ELSE excluded.is_stream END, description = excluded.description',
                        (rec['creator_id'], rec['platform'], rec['content_id'], rec.get('title', ''), rec.get('thumbnail_path', ''), rec.get('thumbnail_url', ''), rec.get('upload_date', ''), rec.get('view_count', 0), int(rec.get('is_short', False)), int(rec.get('is_stream', False)), rec.get('description', ''))
                    )
                    if not existing:
                        new_creator_ids.add(rec['creator_id'])
                for cid in new_creator_ids:
                    self._conn.execute('UPDATE creators SET is_new_activity = 1 WHERE id = ?', (cid,))
                self._conn.commit()
            except (sqlite3.IntegrityError, sqlite3.Error) as exc:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
                raise ValueError(f'Database error in batch upsert: {exc}') from exc
        self._backup()
    def set_verified(self, content_id: str, verified: bool) -> None:
        self._write('UPDATE media_content SET is_verified = ? WHERE content_id = ?', (int(verified), content_id))

    def set_type_override(self, content_id: str, override: str | None) -> None:
        """Manually override the content type for a media item.

        Sets ``type_override`` and updates ``is_short``/``is_stream`` to match.
        When *override* is ``None``, the override is cleared; the next data
        refetch will restore the API-derived classification.

        Args:
            content_id: The YouTube/Twitch content ID.
            override: ``'short'``, ``'video'``, ``'stream'``, or ``None`` to reset.
        """
        if override == 'short':
            self._write(
                'UPDATE media_content SET type_override = ?, is_short = 1, is_stream = 0 WHERE content_id = ?',
                ('short', content_id),
            )
        elif override == 'video':
            self._write(
                'UPDATE media_content SET type_override = ?, is_short = 0, is_stream = 0 WHERE content_id = ?',
                ('video', content_id),
            )
        elif override == 'stream':
            self._write(
                'UPDATE media_content SET type_override = ?, is_short = 0, is_stream = 1 WHERE content_id = ?',
                ('stream', content_id),
            )
        else:
            # Reset: clear the override so the next refetch restores API values
            self._write(
                'UPDATE media_content SET type_override = NULL WHERE content_id = ?',
                (content_id,),
            )

    def get_unverified_media(self) -> list[dict[str, Any]]:
        """Return all media rows where is_verified = 0."""
        return self._read('SELECT content_id, title, description FROM media_content WHERE is_verified = 0')
    def delete_media(self, media_id: int) -> None:
        self._write('DELETE FROM media_content WHERE id = ?', (media_id,))
    def purge_creator_media(self, creator_id: int, platform: str) -> int:
        """Delete all media_content rows for *creator_id* and *platform*.\n\nReturns the number of rows deleted.\n"""
        cur = self._write('DELETE FROM media_content WHERE creator_id = ? AND platform = ?', (creator_id, platform))
        return cur.rowcount
    _SQL_VARIABLE_LIMIT = 500

    def prune_stale_media(self, creator_id: int, platform: str, current_ids: set[str]) -> int:
        """Remove media rows whose content_id is NOT in *current_ids*.

        Preserves ``is_verified`` on remaining rows.  Call after upserting
        the fresh batch of videos so that only stale (deleted-from-platform)
        entries are removed.

        Uses a temporary table approach to avoid the broken chunked-NOT-IN
        pattern.  Previously, chunking ``NOT IN (chunk_1)`` then ``NOT IN
        (chunk_2)`` would delete every row in *chunk_2* (and vice versa)
        because each chunk only "protected" its own subset.

        Safety: if *current_ids* is empty, this is a no-op.  An empty
        set almost always means the fetch was incomplete or failed —
        deleting all media for a creator+platform would be destructive.
        Callers should handle the empty case explicitly if they truly
        want to purge all content.
        """
        if not current_ids:
            return 0
        ids = list(current_ids)
        with self._write_lock:
            # Create a temp table of current IDs, then delete rows
            # NOT in that table.  This avoids the broken chunked-NOT-IN
            # pattern where each chunk would delete rows from other chunks.
            self._conn.execute('CREATE TEMP TABLE IF NOT EXISTS _prune_ids (content_id TEXT PRIMARY KEY)')
            self._conn.execute('DELETE FROM _prune_ids')
            for i in range(0, len(ids), self._SQL_VARIABLE_LIMIT):
                chunk = ids[i:i + self._SQL_VARIABLE_LIMIT]
                placeholders = ','.join('(?)' for _ in chunk)
                self._conn.execute(
                    f'INSERT OR IGNORE INTO _prune_ids (content_id) VALUES {placeholders}',
                    chunk,
                )
            cur = self._conn.execute(
                'DELETE FROM media_content WHERE creator_id = ? AND platform = ? AND content_id NOT IN (SELECT content_id FROM _prune_ids)',
                (creator_id, platform),
            )
            rowcount = cur.rowcount
            self._conn.execute('DELETE FROM _prune_ids')
            self._conn.commit()
        self._backup()
        return rowcount

    # ── Alerts / notifications ────────────────────────────────────────────

    def add_alert(self, creator_id: int, alert_type: str, threshold: int) -> int:
        """Record a triggered alert to prevent re-notification."""
        cur = self._write(
            'INSERT INTO alerts (creator_id, alert_type, threshold, triggered_at) VALUES (?, ?, ?, ?)',
            (creator_id, alert_type, threshold, datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')),
        )
        return cur.lastrowid

    def has_alert(self, creator_id: int, alert_type: str, threshold: int) -> bool:
        """Check if a specific alert has already been triggered."""
        rows = self._read(
            'SELECT 1 FROM alerts WHERE creator_id = ? AND alert_type = ? AND threshold = ?',
            (creator_id, alert_type, threshold),
        )
        return bool(rows)

    def clear_alerts(self) -> None:
        """Clear all triggered alerts (for settings reset)."""
        self._write('DELETE FROM alerts')

    _SUB_MILESTONES = [1000, 5000, 10000, 25000, 50000, 75000, 100000, 250000, 500000, 750000, 1000000]

    def check_view_thresholds(self, creator_id: int, current_views: int) -> list[dict[str, Any]]:
        """Return list of newly crossed view count thresholds for a creator.

        Only checks thresholds configured in the ``notification_view_thresholds`` setting.
        Skips thresholds that have already been alerted.
        """
        thresholds_str = self.get_setting('notification_view_thresholds') or '10000,100000,1000000'
        thresholds = []
        for t in thresholds_str.split(','):
            t = t.strip()
            if t.isdigit():
                thresholds.append(int(t))
        alerts = []
        for t in thresholds:
            if current_views >= t and not self.has_alert(creator_id, 'view_milestone', t):
                self.add_alert(creator_id, 'view_milestone', t)
                alerts.append({'type': 'view_milestone', 'threshold': t, 'creator_id': creator_id})
        return alerts

    def check_subscriber_milestones(self, creator_id: int, current_subs: int) -> list[dict[str, Any]]:
        """Return list of newly crossed subscriber milestones for a creator.

        Checks fixed milestones: 1K, 5K, 10K, 25K, 50K, 75K, 1M.
        Skips milestones that have already been alerted.
        """
        alerts = []
        for m in self._SUB_MILESTONES:
            if current_subs >= m and not self.has_alert(creator_id, 'subscriber_milestone', m):
                self.add_alert(creator_id, 'subscriber_milestone', m)
                alerts.append({'type': 'subscriber_milestone', 'threshold': m, 'creator_id': creator_id})
        return alerts

    # ── Tags ──────────────────────────────────────────────────────────────

    def set_creator_tags(self, creator_id: int, tags: list[str]) -> None:
        """Update the tags field for a creator."""
        self.update_creator(creator_id, tags=json.dumps(tags))

    # ── Activity sparkline ────────────────────────────────────────────────

    def bulk_activity_sparkline(self, weeks: int = 7) -> dict[int, list[int]]:
        """Return {creator_id: [count_per_week]} for the last *weeks* weeks.

        Each element in the list is the number of verified uploads in that
        week period, ordered from oldest to most recent.
        """
        days = weeks * 7
        rows = self._read(
            'SELECT creator_id, '
            '  CAST((julianday(\'now\') - julianday(upload_date)) / 7 AS INTEGER) AS week_offset, '
            '  COUNT(*) AS cnt '
            'FROM media_content '
            'WHERE upload_date != \'\' AND julianday(upload_date) > julianday(\'now\', ?) '
            'GROUP BY creator_id, week_offset '
            'ORDER BY creator_id, week_offset',
            (f'-{days} days',)
        )
        # Get all creator IDs to include those with zero activity
        creators = self.get_creators()
        result: dict[int, list[int]] = {c['id']: [0] * weeks for c in creators}
        for r in rows:
            cid = r['creator_id']
            week_offset = r['week_offset']
            if cid in result and 0 <= week_offset < weeks:
                result[cid][weeks - 1 - week_offset] = r['cnt']
        return result

    # ── Creator lookup for merge/dedup ────────────────────────────────────

    def find_creator_by_link(self, youtube_link: str | None = None, twitch_link: str | None = None) -> int | None:
        """Return creator_id if a creator with matching link exists, else None."""
        if youtube_link:
            rows = self._read(
                'SELECT id FROM creators WHERE youtube_link = ? LIMIT 1',
                (youtube_link,)
            )
            if rows:
                return rows[0]['id']
        if twitch_link:
            rows = self._read(
                'SELECT id FROM creators WHERE twitch_link = ? LIMIT 1',
                (twitch_link,)
            )
            if rows:
                return rows[0]['id']
        return None

    # ── Settings helpers ──────────────────────────────────────────────────

    def get_setting_with_default(self, key: str, default: str) -> str:
        """Return a setting value, falling back to *default* if not found."""
        val = self.get_setting(key)
        return val if val is not None else default

    # ── Profile import / export ──────────────────────────────────────────

    def export_profile(self) -> dict[str, Any]:
        """Export the current profile as a dict suitable for JSON serialization.

        The returned dict includes all creators, media_content, roles, and
        settings (except ``current_profile``).  The ``platforms`` field in
        creator rows is parsed from its JSON-string storage form into a native
        list for readability.

        All reads are performed on the read connection under a single lock
        acquisition to produce a consistent snapshot.
        """
        with self._read_lock:
            creators = [dict(row) for row in self._read_conn.execute('SELECT * FROM creators').fetchall()]
            for c in creators:
                if 'platforms' in c and isinstance(c['platforms'], str):
                    c['platforms'] = json.loads(c['platforms'])
            media = [dict(row) for row in self._read_conn.execute('SELECT * FROM media_content').fetchall()]
            roles = [dict(row) for row in self._read_conn.execute('SELECT * FROM roles').fetchall()]
            settings_rows = [dict(row) for row in self._read_conn.execute("SELECT * FROM settings WHERE key NOT IN ('current_profile', 'api_keys_json')").fetchall()]
        return {
            'version': 1,
            'profile': self._profile,
            'creators': creators,
            'media_content': media,
            'roles': roles,
            'settings': settings_rows,
        }

    def import_profile(self, data: dict[str, Any], profile_name: str) -> None:
        """Import data dict into a **new** profile.

        Creates the profile database, inserts all roles, creators, media, and
        settings.  Raises ``ValueError`` if *profile_name* already exists.
        On failure the new database is deleted and the previous profile is
        restored.
        """
        _validate_profile_name(profile_name)
        if profile_name in self.list_profiles():
            raise ValueError(f'Profile "{profile_name}" already exists')
        if data.get('version') != 1:
            raise ValueError('Unsupported profile format version')
        old_profile = self._profile
        try:
            self.switch_profile(profile_name)
            for role in data.get('roles', []):
                self._write(
                    'INSERT INTO roles (id, role_name, role_color) VALUES (?, ?, ?)',
                    (role['id'], role['role_name'], role['role_color']),
                )
            for c in data.get('creators', []):
                platforms = c.get('platforms', [])
                if isinstance(platforms, list):
                    platforms = json.dumps(platforms)
                tags_json = json.dumps(c.get('tags', [])) if isinstance(c.get('tags'), list) else (c.get('tags') or '[]')
                self._write(
                    'INSERT INTO creators (id, nickname, platforms, role_id, youtube_type, '
                    'youtube_channel_id, youtube_link, twitch_link, pfp_url, date_added, is_new_activity, notes, tags) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (c['id'], c['nickname'], platforms, c.get('role_id'),
                     c.get('youtube_type'), c.get('youtube_channel_id'),
                     c.get('youtube_link'), c.get('twitch_link'), c.get('pfp_url'),
                     c.get('date_added'), c.get('is_new_activity', 0),
                     c.get('notes', ''), tags_json),
                )
            for m in data.get('media_content', []):
                self._write(
                    'INSERT INTO media_content (creator_id, platform, content_id, title, '
                    'thumbnail_path, thumbnail_url, upload_date, view_count, is_verified, '
                    'is_short, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (m['creator_id'], m['platform'], m['content_id'], m.get('title', ''),
                     m.get('thumbnail_path', ''), m.get('thumbnail_url', ''),
                     m.get('upload_date', ''), m.get('view_count', 0),
                     m.get('is_verified', 0), m.get('is_short', 0), m.get('description', '')),
                )
            for s in data.get('settings', []):
                key = s.get('key', '')
                if key in ('current_profile', 'api_keys_json'):
                    continue
                self._write(
                    'INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
                    (key, s.get('value', '')),
                )
        except Exception:
            # Roll back: delete the new database and switch back
            try:
                self.switch_profile(old_profile)
            except Exception:
                pass
            db_path = STORAGE_DIR / f'{profile_name}.db'
            try:
                db_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    # ── Creator export / import ──────────────────────────────────────────

    def export_creator(self, creator_id: int) -> dict[str, Any]:
        """Export a single creator's data as a dict for sharing.

        Includes the creator record, all their media content, and subscriber /
        follower counts from the settings table.
        """
        creator = self.get_creator(creator_id)
        if not creator:
            raise ValueError(f'Creator {creator_id} not found')
        media = self.get_media(creator_id=creator_id)
        platforms = json.loads(creator.get('platforms', '[]')) if isinstance(creator.get('platforms'), str) else creator.get('platforms', [])
        stats: dict[str, int] = {}
        if 'youtube' in platforms:
            raw = self.get_setting(f'yt_channel_subscribers_{creator_id}')
            if raw and raw.isdigit():
                stats['youtube_subscribers'] = int(raw)
            raw_views = self.get_setting(f'yt_channel_views_{creator_id}')
            if raw_views and raw_views.isdigit():
                stats['youtube_views'] = int(raw_views)
        if 'twitch' in platforms:
            raw = self.get_setting(f'twitch_followers_{creator_id}')
            if raw and raw.isdigit():
                stats['twitch_followers'] = int(raw)
        # Ensure platforms is a list for JSON readability
        creator_copy = dict(creator)
        creator_copy['platforms'] = platforms
        # Include role name so importing profiles can map by name.
        role = self.get_role(creator.get('role_id')) if creator.get('role_id') else None
        if role:
            creator_copy['role_name'] = role['role_name']
        return {
            'version': 1,
            'type': 'creator',
            'creator': creator_copy,
            'media_content': media,
            'stats': stats,
            'community_description': self.get_setting('community_description') or '',
        }

    def import_creator(self, data: dict[str, Any]) -> int:
        """Import a single creator from a data dict into the current profile.

        Maps the exported role name to an existing role in the current profile,
        falling back to the first available role.  Returns the new creator ID.
        """
        if data.get('type') != 'creator':
            raise ValueError('Not a creator export file')
        c = data['creator']
        platforms = c.get('platforms', [])
        if isinstance(platforms, list):
            platforms_json = json.dumps(platforms)
        else:
            platforms_json = platforms
            platforms = json.loads(platforms)
        # Map role by name from the export data, falling back to the first role.
        roles = self.get_roles()
        target_role_id = None
        source_role_name = c.get('role_name')
        if source_role_name:
            for r in roles:
                if r['role_name'] == source_role_name:
                    target_role_id = r['id']
                    break
        if target_role_id is None and roles:
            target_role_id = roles[0]['id']
        elif target_role_id is None:
            raise ValueError('No roles available. Create a role first.')
        new_id = self.add_creator(
            nickname=c['nickname'],
            role_id=target_role_id,
            platforms=platforms,
            youtube_channel_id=c.get('youtube_channel_id'),
            youtube_link=c.get('youtube_link'),
            twitch_link=c.get('twitch_link'),
            pfp_url=c.get('pfp_url'),
            notes=c.get('notes', ''),
            tags=c.get('tags') if isinstance(c.get('tags'), list) else None,
        )
        # Import community description if present and current profile has none
        imported_desc = data.get('community_description', '')
        if imported_desc and not (self.get_setting('community_description') or '').strip():
            self.set_setting('community_description', imported_desc)
        # Import media content
        for m in data.get('media_content', []):
            self.add_media(
                creator_id=new_id,
                platform=m['platform'],
                content_id=m['content_id'],
                title=m.get('title', ''),
                thumbnail_path=m.get('thumbnail_path', ''),
                upload_date=m.get('upload_date', ''),
                view_count=m.get('view_count', 0),
                is_verified=bool(m.get('is_verified', 0)),
                is_short=bool(m.get('is_short', 0)),
                is_stream=bool(m.get('is_stream', 0)),
                thumbnail_url=m.get('thumbnail_url', ''),
                description=m.get('description', ''),
            )
        # Import stats
        stats = data.get('stats', {})
        if 'youtube_subscribers' in stats:
            self.set_setting(f'yt_channel_subscribers_{new_id}', str(stats['youtube_subscribers']))
        if 'youtube_views' in stats:
            self.set_setting(f'yt_channel_views_{new_id}', str(stats['youtube_views']))
        if 'twitch_followers' in stats:
            self.set_setting(f'twitch_followers_{new_id}', str(stats['twitch_followers']))
        return new_id

    def close(self) -> None:
        with self._write_lock:
            with self._read_lock:
                if self._read_conn is not None:
                    self._read_conn.close()
                    self._read_conn = None
                if self._conn is not None:
                    self._conn.close()
                    self._conn = None
    def __enter__(self) -> DatabaseManager:
        return self
    def __exit__(self, *exc: Any) -> None:
        self.close()

def determine_startup_profile() -> str:
    """Return the profile to open on startup.

    Uses ``last_profile`` from global settings if available, falling back
    to ``'default'``.  If the remembered profile database doesn't exist,
    falls back to ``'default'``.
    """
    with _GLOBAL_LOCK:
        settings = _read_global_settings()
    last = settings.get('last_profile', 'default')
    if (STORAGE_DIR / f'{last}.db').exists():
        return last
    return 'default'

def _run_self_test() -> None:
    """Verify schema creation, CRUD, profile switching, and backup."""
    import tempfile
    import os
    from . import paths as _paths_mod
    import core.db_manager as _self_mod
    tmp = Path(tempfile.mkdtemp())
    _paths_mod.STORAGE_DIR = tmp / 'storage'
    _paths_mod.BACKUPS_DIR = tmp / 'storage' / 'backups'
    _paths_mod.GLOBAL_SETTINGS_PATH = _paths_mod.STORAGE_DIR / 'global_settings.json'
    _self_mod.STORAGE_DIR = _paths_mod.STORAGE_DIR
    _self_mod.BACKUPS_DIR = _paths_mod.BACKUPS_DIR
    _self_mod.GLOBAL_SETTINGS_PATH = _paths_mod.GLOBAL_SETTINGS_PATH
    print(f'Test dir: {tmp}')
    db = DatabaseManager('default')
    print(f'Active profile: {db.profile}')
    assert db.profile == 'default'
    assert (STORAGE_DIR / 'default.db').exists()
    db.set_global_setting('api_keys_json', '{\"yt\": \"key123\"}')
    assert db.get_global_setting('api_keys_json') == '{\"yt\": \"key123\"}'
    rid = db.add_role('Streamer', '#FF5733')
    role = db.get_role(rid)
    assert role['role_name'] == 'Streamer'
    db.update_role(rid, role_color='#00FF00')
    assert db.get_role(rid)['role_color'] == '#00FF00'
    cid = db.add_creator('TestNick', rid, ['youtube', 'twitch'], youtube_link='https://www.youtube.com/channel/UC_test')
    creator = db.get_creator(cid)
    assert creator['nickname'] == 'TestNick'
    assert json.loads(creator['platforms']) == ['youtube', 'twitch']
    assert creator['youtube_link'] == 'https://www.youtube.com/channel/UC_test'
    mid = db.add_media(cid, 'youtube', 'vid001', 'First Video', is_verified=True)
    assert db.get_media_by_content_id('vid001')['is_verified'] == 1
    db.upsert_media(cid, 'youtube', 'vid001', 'Updated Title', view_count=42)
    rec = db.get_media_by_content_id('vid001')
    assert rec['title'] == 'Updated Title'
    assert rec['is_verified'] == 1, 'upsert must preserve is_verified'
    assert rec['view_count'] == 42
    db.switch_profile('gaming_team')
    assert db.profile == 'gaming_team'
    assert (STORAGE_DIR / 'gaming_team.db').exists()
    assert db.list_profiles() == ['default', 'gaming_team']
    assert db.get_creators() == []
    db.add_role('ToDelete', '#111111')
    del_rid = db.add_role('ToDelete2', '#222222')
    db.add_creator('Ghost', del_rid, ['youtube'])
    try:
        db.delete_role(del_rid)
        assert False, 'Should have raised ValueError'
    except ValueError:
        pass
    db.delete_creator(db.get_creators()[0]['id'])
    db.delete_role(del_rid)
    try:
        db.add_media(999, 'youtube', 'bad_fk', 'No creator')
        assert False, 'Should have raised ValueError for FK violation'
    except ValueError:
        pass
    db.close()
    # Test determine_startup_profile
    assert determine_startup_profile() == 'gaming_team', f'Expected gaming_team, got {determine_startup_profile()}'
    # Test that switching profiles persists to global settings
    db2 = DatabaseManager('default')
    assert determine_startup_profile() == 'default', f'Expected default after switch, got {determine_startup_profile()}'
    # Test global API keys survive a profile switch
    db2.set_global_setting('api_keys_json', '{"yt": "test_key_12345"}')
    db2.switch_profile('gaming_team')
    assert db2.get_global_setting('api_keys_json') == '{"yt": "test_key_12345"}', 'Global keys should survive profile switch'
    db2.close()
    shutil.rmtree(tmp)
    print('All self-tests passed.')
if __name__ == '__main__':
    _run_self_test()