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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from .paths import BACKUPS_DIR, GLOBAL_SETTINGS_PATH, STORAGE_DIR, THUMBNAILS_DIR

logger = logging.getLogger(__name__)
MAX_BACKUPS = 3
_BACKUP_DEBOUNCE_S = 60.0
_PROFILE_RE = re.compile(r'^[A-Za-z0-9 _-]+$')


def _constrain_cache_path(value: str | None) -> str:
    """Return *value* only if it is a safe cache path; otherwise ''.

    Local paths are resolved and required to live inside ``THUMBNAILS_DIR`` so
    an imported profile/creator can't point the app at an arbitrary local file
    (path-traversal / arbitrary-file-read).  Remote URLs (``http://`` /
    ``https://``) and empty values pass through unchanged.
    """
    if not value:
        return ''
    if isinstance(value, str) and value.startswith(('http://', 'https://')):
        return value
    try:
        resolved = Path(value).expanduser().resolve()
        resolved.relative_to(THUMBNAILS_DIR.resolve())
    except (OSError, ValueError):
        return ''
    return value


def _utc_now() -> str:
    """Return the current UTC time as an ISO 8601 string (``Z`` suffix).

    Matches the ``strftime('%Y-%m-%dT%H:%M:%SZ', 'now')`` SQL defaults
    used across the schema so Python-side and DB-side timestamps agree.
    """
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _validate_profile_name(name: str) -> None:
    """Raise ValueError if *name* contains path separators or unsafe chars."""
    if not name or not _PROFILE_RE.match(name):
        raise ValueError(
            f'Invalid profile name: {name!r}. '
            'Use only letters, numbers, spaces, hyphens, and underscores.'
        )

_GLOBAL_LOCK = threading.Lock()
_GLOBAL_DEFAULTS: dict[str, str] = {'last_profile': 'default', 'api_keys_json': '{}', 'first_run_complete': '', 'ollama_host': ''}


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
_SCHEMA = '\nCREATE TABLE IF NOT EXISTS settings (\n    key     TEXT PRIMARY KEY,\n    value   TEXT NOT NULL\n);\n\nCREATE TABLE IF NOT EXISTS roles (\n    id          INTEGER PRIMARY KEY AUTOINCREMENT,\n    role_name   TEXT    NOT NULL UNIQUE,\n    role_color  TEXT    NOT NULL\n);\n\nCREATE TABLE IF NOT EXISTS creators (\n    id            INTEGER PRIMARY KEY AUTOINCREMENT,\n    nickname      TEXT    NOT NULL,\n    platforms     TEXT    NOT NULL DEFAULT \'[]\',\n    role_id       INTEGER NOT NULL,\n    youtube_type  TEXT,\n    youtube_channel_id TEXT,\n    youtube_link  TEXT,\n    twitch_link   TEXT,\n    pfp_url       TEXT,\n    date_added       TEXT    NOT NULL DEFAULT (strftime(\'%Y-%m-%dT%H:%M:%SZ\', \'now\')),\n    is_new_activity  INTEGER NOT NULL DEFAULT 0,\n    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE RESTRICT\n);\n\nCREATE TABLE IF NOT EXISTS media_content (\n    id              INTEGER PRIMARY KEY AUTOINCREMENT,\n    creator_id      INTEGER NOT NULL,\n    platform        TEXT    NOT NULL CHECK(platform IN (\'youtube\', \'twitch\')),\n    content_id      TEXT    NOT NULL UNIQUE,\n    title           TEXT    NOT NULL DEFAULT \'\',\n    thumbnail_path  TEXT    NOT NULL DEFAULT \'\',\n    thumbnail_url   TEXT    NOT NULL DEFAULT \'\',\n    upload_date     TEXT    NOT NULL DEFAULT \'\',\n    view_count      INTEGER NOT NULL DEFAULT 0,\n    is_verified     INTEGER NOT NULL DEFAULT 0,\n    is_short        INTEGER NOT NULL DEFAULT 0,\n    is_stream       INTEGER NOT NULL DEFAULT 0,\n    type_override   TEXT    DEFAULT NULL,\n    description     TEXT    NOT NULL DEFAULT \'\',\n    FOREIGN KEY (creator_id) REFERENCES creators(id) ON DELETE CASCADE\n);\n\nCREATE INDEX IF NOT EXISTS idx_media_creator  ON media_content(creator_id);\nCREATE INDEX IF NOT EXISTS idx_media_platform  ON media_content(platform);\nCREATE INDEX IF NOT EXISTS idx_content_id      ON media_content(content_id);\nCREATE INDEX IF NOT EXISTS idx_media_verified ON media_content(is_verified);\n'
_SCHEMA_VERSION = 9  # Increment when adding new migrations

# Migrate old invalid Anthropic model IDs to valid API identifiers.
_MODEL_ID_MIGRATION = {
    'claude-haiku-4-5': 'claude-haiku-4-5-20251001',
}

_DEFAULT_SETTINGS = {'community_name': '', 'community_description': '', 'auto_verify_model': 'claude-haiku-4-5-20251001', 'verify_keywords': '', 'fetch_video_limit': '50', 'thumbnail_quality': 'low', 'notifications_enabled': '0', 'notification_view_thresholds': '10000,100000,1000000', 'discover_sub_ceiling': '0', 'discover_min_subscribers': '0', 'discover_min_views_per_sub': '10', 'discover_default_sort': 'potential', 'discover_shorts': 'ask', 'discover_notifications': '1'}
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
        if version == 7:
            # v6→v7: add creator_snapshots for trend arrows / smart alerts, and
            # widen the alerts CHECK to admit 'velocity_spike' and 'inactivity'.
            # SQLite cannot ALTER a CHECK constraint, so rename→recreate→copy→drop.
            conn.execute(
                'CREATE TABLE IF NOT EXISTS creator_snapshots ('
                'id INTEGER PRIMARY KEY AUTOINCREMENT, '
                'creator_id INTEGER NOT NULL, '
                'captured_at TEXT NOT NULL, '
                'view_total INTEGER NOT NULL DEFAULT 0, '
                'subscriber_total INTEGER NOT NULL DEFAULT 0, '
                'FOREIGN KEY (creator_id) REFERENCES creators(id) ON DELETE CASCADE, '
                'UNIQUE (creator_id, captured_at))'
            )
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_snapshots_creator_date '
                'ON creator_snapshots(creator_id, captured_at DESC)'
            )
            # Widen the alerts CHECK (only if the old narrow one is in place).
            cols = [row['name'] for row in conn.execute('PRAGMA table_info(alerts)')]
            if cols:
                conn.execute('ALTER TABLE alerts RENAME TO alerts_old_v6')
                conn.execute(
                    'CREATE TABLE alerts ('
                    'id INTEGER PRIMARY KEY AUTOINCREMENT, '
                    'creator_id INTEGER NOT NULL, '
                    "alert_type TEXT NOT NULL CHECK(alert_type IN ("
                    "'view_milestone', 'subscriber_milestone', 'velocity_spike', 'inactivity')), "
                    'threshold INTEGER NOT NULL, '
                    "triggered_at TEXT NOT NULL DEFAULT '', "
                    'FOREIGN KEY (creator_id) REFERENCES creators(id) ON DELETE CASCADE)'
                )
                conn.execute(
                    'INSERT INTO alerts (creator_id, alert_type, threshold, triggered_at) '
                    'SELECT creator_id, alert_type, threshold, triggered_at FROM alerts_old_v6'
                )
                conn.execute(
                    'CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_unique '
                    'ON alerts(creator_id, alert_type, threshold)'
                )
                conn.execute('DROP TABLE alerts_old_v6')
        if version == 8:
            # v7→v8: Market Research / Recruitment.  Four new tables for the
            # Discover feature — all per-profile, isolated from the tracked
            # roster.  See core/discover_worker.py and ui/discover_window.py.
            conn.execute(
                'CREATE TABLE IF NOT EXISTS search_cache ('
                'id INTEGER PRIMARY KEY AUTOINCREMENT, '
                'query_hash TEXT NOT NULL, '
                'params_json TEXT NOT NULL, '
                'created_at TEXT NOT NULL DEFAULT (strftime(\'%Y-%m-%dT%H:%M:%SZ\', \'now\')), '
                'results_json TEXT NOT NULL DEFAULT \'[]\')'
            )
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_search_cache_hash '
                'ON search_cache(query_hash)'
            )
            conn.execute(
                'CREATE TABLE IF NOT EXISTS discovered_creators ('
                'id INTEGER PRIMARY KEY AUTOINCREMENT, '
                'channel_id TEXT NOT NULL UNIQUE, '
                'handle TEXT NOT NULL DEFAULT \'\', '
                'title TEXT NOT NULL DEFAULT \'\', '
                'pfp_url TEXT NOT NULL DEFAULT \'\', '
                'subscriber_count INTEGER NOT NULL DEFAULT 0, '
                'view_count INTEGER NOT NULL DEFAULT 0, '
                'video_count INTEGER NOT NULL DEFAULT 0, '
                'cadence_per_week REAL NOT NULL DEFAULT 0, '
                'growth_signal REAL NOT NULL DEFAULT 0, '
                'engagement REAL NOT NULL DEFAULT 0, '
                'niche_fit REAL NOT NULL DEFAULT 0, '
                'views_per_sub REAL NOT NULL DEFAULT 0, '
                'potential_score INTEGER NOT NULL DEFAULT 0, '
                'recent_titles_json TEXT NOT NULL DEFAULT \'[]\', '
                'is_short_channel INTEGER NOT NULL DEFAULT 0, '
                'first_discovered_at TEXT NOT NULL DEFAULT (strftime(\'%Y-%m-%dT%H:%M:%SZ\', \'now\')), '
                'last_refreshed_at TEXT NOT NULL DEFAULT \'\')'
            )
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_discovered_channel '
                'ON discovered_creators(channel_id)'
            )
            conn.execute(
                'CREATE TABLE IF NOT EXISTS candidate_pool ('
                'id INTEGER PRIMARY KEY AUTOINCREMENT, '
                'channel_id TEXT NOT NULL UNIQUE, '
                'notes TEXT NOT NULL DEFAULT \'\', '
                'flagged_at TEXT NOT NULL DEFAULT (strftime(\'%Y-%m-%dT%H:%M:%SZ\', \'now\')), '
                'last_updated_at TEXT NOT NULL DEFAULT \'\', '
                'FOREIGN KEY (channel_id) REFERENCES discovered_creators(channel_id) ON DELETE CASCADE)'
            )
            conn.execute(
                'CREATE TABLE IF NOT EXISTS ai_evaluations ('
                'id INTEGER PRIMARY KEY AUTOINCREMENT, '
                'channel_id TEXT NOT NULL, '
                'provider TEXT NOT NULL, '
                'model TEXT NOT NULL, '
                'verdict TEXT NOT NULL DEFAULT \'\', '
                'rationale TEXT NOT NULL DEFAULT \'\', '
                'created_at TEXT NOT NULL DEFAULT (strftime(\'%Y-%m-%dT%H:%M:%SZ\', \'now\')), '
                'FOREIGN KEY (channel_id) REFERENCES discovered_creators(channel_id) ON DELETE CASCADE)'
            )
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_ai_eval_channel '
                'ON ai_evaluations(channel_id, created_at DESC)'
            )
        if version == 9:
            # v8→v9: Performance indexes.  idx_media_verified speeds the
            # Verify / keyword-verify queries that filter on is_verified, and
            # the partial idx_creators_new_activity speeds the "new activity"
            # badge lookup (the table is almost always 0 for this column, so a
            # partial index stays tiny).  Both are CREATE IF NOT EXISTS so they
            # apply cleanly to fresh databases (which run every migration) and
            # to existing ones upgrading from v8.
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_media_verified '
                'ON media_content(is_verified)'
            )
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_creators_new_activity '
                'ON creators(is_new_activity) WHERE is_new_activity = 1'
            )
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

    def clear_backups(self) -> int:
        """Delete every profile backup file in BACKUPS_DIR.

        Backups are the timestamped ``*.db.bak`` files written by
        :meth:`_backup_locked`.  Removing them frees disk space but loses
        the automatic point-in-time snapshots; new backups are created on
        future writes.  Returns the number of backup files removed.
        """
        removed = 0
        if BACKUPS_DIR.exists():
            for f in BACKUPS_DIR.glob('*.db.bak'):
                try:
                    f.unlink(missing_ok=True)
                    removed += 1
                except OSError as exc:
                    logger.warning('Failed to delete backup %s: %s', f, exc)
        return removed

    def get_all_thumbnail_paths(self) -> list[str]:
        """Return all non-empty thumbnail_path values from media_content."""
        return [
            row['thumbnail_path']
            for row in self._read("SELECT thumbnail_path FROM media_content WHERE thumbnail_path != ''")
            if row['thumbnail_path']
        ]
    def get_all_inuse_thumbnail_paths(self) -> list[str]:
        """Return cached-image file paths referenced by ANY profile's database.

        The thumbnail cache (THUMBNAILS_DIR) is shared across all profiles, so
        cache pruning must consider every profile — a file still referenced
        by another profile is in use and must not be deleted.  Returns the
        union of ``creators.pfp_url`` and ``media_content.thumbnail_path``
        across every profile database, opening each read-only so the active
        profile is never disturbed.
        """
        paths: set[str] = set()
        for profile in self.list_profiles():
            db_path = STORAGE_DIR / f'{profile}.db'
            if not db_path.exists():
                continue
            try:
                conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=5.0, check_same_thread=False)
            except sqlite3.Error:
                continue
            try:
                try:
                    for (p,) in conn.execute("SELECT pfp_url FROM creators WHERE pfp_url IS NOT NULL AND pfp_url <> ''"):
                        if p:
                            paths.add(p)
                except sqlite3.OperationalError:
                    pass
                try:
                    for (p,) in conn.execute("SELECT thumbnail_path FROM media_content WHERE thumbnail_path IS NOT NULL AND thumbnail_path <> ''"):
                        if p:
                            paths.add(p)
                except sqlite3.OperationalError:
                    pass
            finally:
                conn.close()
        return list(paths)
    def _backup(self) -> None:
        """Create a timestamped backup and prune to MAX_BACKUPS.

        Acquires ``_write_lock`` and delegates to ``_backup_locked``.  Use
        this from callers that are not already holding the write lock.
        """
        with self._write_lock:
            self._backup_locked()

    def _backup_locked(self) -> None:
        """Create a timestamped backup and prune to MAX_BACKUPS.

        Assumes the caller already holds ``_write_lock``.  Checkpoints the
        WAL so the .db file contains all committed data, then offloads the
        file copy to a background thread so reads aren't blocked.

        Note: the file copy happens outside the lock (in the spawned thread),
        so new writes between the checkpoint and the copy are not captured.
        This is acceptable for a best-effort point-in-time backup — the
        backup reflects all data committed before the checkpoint.
        """
        now = time.monotonic()
        if now - self._last_backup_time < _BACKUP_DEBOUNCE_S:
            return
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
            # Run the debounced checkpoint/backup while still holding the
            # lock, instead of releasing and immediately re-acquiring it on
            # every write (the old _write → _backup() path).  This removes a
            # lock cycle per write and a window where another writer could
            # interleave between the commit and the checkpoint.
            self._backup_locked()
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
    def bulk_view_totals(self) -> dict[int, int]:
        """Return {creator_id: SUM(view_count)} for all creators in one query.

        Use instead of per-creator ``get_media`` + ``sum()`` when only the
        total view count is needed (e.g. milestone checks).
        """
        rows = self._read(
            'SELECT creator_id, COALESCE(SUM(view_count), 0) AS total '
            'FROM media_content GROUP BY creator_id'
        )
        return {r['creator_id']: r['total'] for r in rows}
    def bulk_media_stats(self, content_clause: str = '', date_clause: str = '') -> dict[int, tuple[int, int]]:
        """Return {creator_id: (total_views, count)} for media matching the clauses.

        Replaces per-creator ``SUM``/``COUNT`` queries (an N+1 pattern in the
        report generators) with a single ``GROUP BY`` pass.  *content_clause*
        and *date_clause* are pre-built ``AND ...`` fragments produced by
        ``report_generator._build_filter_clause`` and the date-range builders;
        both may be empty strings.
        """
        rows = self._read(
            f"SELECT creator_id, COALESCE(SUM(view_count), 0) AS views, COUNT(*) AS count "
            f"FROM media_content WHERE 1=1 {content_clause} {date_clause} GROUP BY creator_id"
        )
        return {r['creator_id']: (r['views'], r['count']) for r in rows}
    def bulk_new_activity_creators(self) -> set[int]:
        """Return set of creator IDs flagged with new-activity alert."""
        rows = self._read('SELECT id FROM creators WHERE is_new_activity = 1')
        return {r['id'] for r in rows}

    def bulk_subscriber_counts(self, creators: list[dict[str, Any]] | None = None) -> dict[int, dict[str, int]]:
        """Return {creator_id: {'youtube': subs, 'twitch': followers}} for all creators.

        Values are 0 when no data has been fetched yet.  Pass *creators* (the
        list returned by :meth:`get_creators`) to skip a redundant re-fetch when
        the caller already has it.
        """
        if creators is None:
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

    def get_api_keys(self) -> dict[str, str]:
        """Return the decrypted API-key dict from the global ``api_keys_json``.

        Handles one-time migration of legacy plaintext values: if the stored
        value isn't ``dpapi:``-prefixed, it is parsed, re-stored encrypted via
        :meth:`set_api_keys`, and returned.  Always returns a dict (possibly
        empty) and never raises.
        """
        import json as _json
        from .secrets import decrypt, encrypt
        raw = self.get_global_setting('api_keys_json') or '{}'
        # Legacy plaintext (no dpapi: prefix) — parse, re-encrypt, re-store.
        if raw and not raw.startswith('dpapi:'):
            try:
                parsed = _json.loads(raw)
                keys = {k: v for k, v in parsed.items() if isinstance(v, str)} if isinstance(parsed, dict) else {}
            except (ValueError, _json.JSONDecodeError):
                keys = {}
            self.set_api_keys(keys)
            return keys
        plaintext = decrypt(raw)
        if not plaintext:
            return {}
        try:
            parsed = _json.loads(plaintext)
            return {k: v for k, v in parsed.items() if isinstance(v, str)} if isinstance(parsed, dict) else {}
        except (ValueError, _json.JSONDecodeError):
            return {}

    def set_api_keys(self, keys: dict[str, str]) -> None:
        """Persist *keys* to the global ``api_keys_json``, DPAPI-encrypted."""
        import json as _json
        from .secrets import encrypt
        token = encrypt(_json.dumps(keys))
        self.set_global_setting('api_keys_json', token)
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
    def add_media(self, creator_id: int, platform: str, content_id: str, title: str='', thumbnail_path: str='', upload_date: str='', view_count: int=0, is_verified: bool=False, is_short: bool=False, is_stream: bool=False, thumbnail_url: str='', description: str='', type_override: str | None=None) -> int:
        cur = self._write('INSERT INTO media_content (creator_id, platform, content_id, title, thumbnail_path, thumbnail_url, upload_date, view_count, is_verified, is_short, is_stream, description, type_override) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (creator_id, platform, content_id, title, thumbnail_path, thumbnail_url, upload_date, view_count, int(is_verified), int(is_short), int(is_stream), description, type_override))
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
        content_ids = [rec['content_id'] for rec in records]
        with self._write_lock:
            try:
                # Pre-fetch existing content_ids in one chunked IN(...) query
                # so we can decide which records are genuinely new without a
                # per-record SELECT (halves the statements inside the lock).
                existing_ids: set[str] = set()
                for i in range(0, len(content_ids), 500):
                    chunk = content_ids[i:i + 500]
                    placeholders = ','.join('?' * len(chunk))
                    existing_ids.update(
                        row[0] for row in self._conn.execute(
                            f'SELECT content_id FROM media_content WHERE content_id IN ({placeholders})',
                            tuple(chunk),
                        )
                    )
                upsert_sql = (
                    'INSERT INTO media_content (creator_id, platform, content_id, title, thumbnail_path, thumbnail_url, upload_date, view_count, is_verified, is_short, is_stream, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?) '
                    'ON CONFLICT(content_id) DO UPDATE SET '
                    'title = excluded.title, thumbnail_path = excluded.thumbnail_path, thumbnail_url = excluded.thumbnail_url, upload_date = excluded.upload_date, view_count = excluded.view_count, '
                    'is_short = CASE WHEN media_content.type_override IS NOT NULL THEN media_content.is_short ELSE excluded.is_short END, '
                    'is_stream = CASE WHEN media_content.type_override IS NOT NULL THEN media_content.is_stream ELSE excluded.is_stream END, '
                    'description = excluded.description'
                )
                upsert_params = [
                    (rec['creator_id'], rec['platform'], rec['content_id'], rec.get('title', ''),
                     rec.get('thumbnail_path', ''), rec.get('thumbnail_url', ''), rec.get('upload_date', ''),
                     rec.get('view_count', 0), int(rec.get('is_short', False)), int(rec.get('is_stream', False)),
                     rec.get('description', ''))
                    for rec in records
                ]
                self._conn.executemany(upsert_sql, upsert_params)
                new_creator_ids = {rec['creator_id'] for rec in records if rec['content_id'] not in existing_ids}
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

    def set_verified_if_profile(self, content_id: str, verified: bool, expected_profile: str) -> bool:
        """Atomically mark *content_id* verified only if the active profile still
        matches *expected_profile*.

        The profile check and the UPDATE run under a single ``_write_lock``
        acquisition so a ``switch_profile`` (which swaps ``self._conn`` under
        that same lock) cannot slip between them and redirect the write into the
        wrong profile's database. Returns ``True`` if the row was written,
        ``False`` if the profile has changed (caller should abort the run).
        """
        if self._conn is None:
            raise RuntimeError('DatabaseManager is closed')
        with self._write_lock:
            if self._profile != expected_profile:
                return False
            try:
                self._conn.execute(
                    'UPDATE media_content SET is_verified = ? WHERE content_id = ?',
                    (int(verified), content_id),
                )
                self._conn.commit()
            except sqlite3.Error as exc:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
                raise ValueError(f'Database error: {exc}') from exc
            self._backup_locked()
        return True

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

    def get_unverified_media(self, creator_id: int | None = None) -> list[dict[str, Any]]:
        """Return media rows where is_verified = 0.

        When *creator_id* is given, only that creator's unverified media is
        returned (used by the per-creator Verify button in Media History);
        otherwise every unverified row across all creators is returned.
        """
        if creator_id is None:
            return self._read('SELECT content_id, title, description FROM media_content WHERE is_verified = 0')
        return self._read(
            'SELECT content_id, title, description FROM media_content WHERE is_verified = 0 AND creator_id = ?',
            (creator_id,),
        )
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

    def existing_alerts(self, creator_ids: list[int], alert_type: str) -> set[tuple[int, int]]:
        """Return a set of ``(creator_id, threshold)`` already-triggered alerts
        of *alert_type* for the given creators, in one (chunked) query.

        Replaces per-creator :meth:`has_alert` calls in the milestone/velocity/
        inactivity detectors so an N-creator check issues one SELECT instead
        of N.
        """
        result: set[tuple[int, int]] = set()
        if not creator_ids:
            return result
        ids = list(creator_ids)
        for i in range(0, len(ids), self._SQL_VARIABLE_LIMIT):
            chunk = ids[i:i + self._SQL_VARIABLE_LIMIT]
            placeholders = ','.join('?' * len(chunk))
            rows = self._read(
                f'SELECT creator_id, threshold FROM alerts '
                f'WHERE alert_type = ? AND creator_id IN ({placeholders})',
                (alert_type, *chunk),
            )
            result.update((r['creator_id'], r['threshold']) for r in rows)
        return result

    def add_alerts(self, rows: list[tuple[int, str, int]]) -> None:
        """Batch-insert triggered alerts in one transaction.

        *rows* is a list of ``(creator_id, alert_type, threshold)`` tuples.
        Replaces per-alert :meth:`add_alert` calls so an N-creator milestone
        pass issues one INSERT (executemany) instead of N.
        """
        if not rows:
            return
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        payload = [(cid, atype, thr, now) for (cid, atype, thr) in rows]
        with self._write_lock:
            try:
                self._conn.executemany(
                    'INSERT INTO alerts (creator_id, alert_type, threshold, triggered_at) VALUES (?, ?, ?, ?)',
                    payload,
                )
                self._conn.commit()
            except sqlite3.Error as exc:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
                raise ValueError(f'Database error: {exc}') from exc
            self._backup_locked()

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

    def check_subscriber_milestones_bulk(
        self, creators: list[dict[str, Any]], sub_counts: dict[int, dict[str, int]]
    ) -> list[dict[str, Any]]:
        """Bulk version of :meth:`check_subscriber_milestones` for all creators.

        Issues one :meth:`existing_alerts` SELECT and one :meth:`add_alerts`
        INSERT instead of N per-creator has_alert/add_alert round-trips.
        *sub_counts* is the dict returned by :meth:`bulk_subscriber_counts`.
        """
        cids = [c['id'] for c in creators]
        existing = self.existing_alerts(cids, 'subscriber_milestone')
        new_alerts: list[dict[str, Any]] = []
        new_rows: list[tuple[int, str, int]] = []
        for c in creators:
            cid = c['id']
            counts = sub_counts.get(cid, {})
            max_subs = max(counts.get('youtube', 0), counts.get('twitch', 0))
            if max_subs <= 0:
                continue
            for m in self._SUB_MILESTONES:
                if max_subs >= m and (cid, m) not in existing:
                    new_alerts.append({'type': 'subscriber_milestone', 'threshold': m, 'creator_id': cid})
                    new_rows.append((cid, 'subscriber_milestone', m))
        self.add_alerts(new_rows)
        return new_alerts

    def check_view_thresholds_bulk(
        self,
        creators: list[dict[str, Any]],
        view_totals: dict[int, int],
        thresholds: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Bulk version of :meth:`check_view_thresholds` for all creators.

        *thresholds* may be passed in (parsed once by the caller) to avoid
        re-reading the ``notification_view_thresholds`` setting per creator.
        """
        if thresholds is None:
            thresholds_str = self.get_setting('notification_view_thresholds') or '10000,100000,1000000'
            thresholds = [int(t.strip()) for t in thresholds_str.split(',') if t.strip().isdigit()]
        cids = [c['id'] for c in creators]
        existing = self.existing_alerts(cids, 'view_milestone')
        new_alerts: list[dict[str, Any]] = []
        new_rows: list[tuple[int, str, int]] = []
        for c in creators:
            cid = c['id']
            total = view_totals.get(cid, 0)
            if total <= 0:
                continue
            for t in thresholds:
                if total >= t and (cid, t) not in existing:
                    new_alerts.append({'type': 'view_milestone', 'threshold': t, 'creator_id': cid})
                    new_rows.append((cid, 'view_milestone', t))
        self.add_alerts(new_rows)
        return new_alerts

    # ── Creator snapshots (trend arrows + smart alerts) ────────────────

    _SNAPSHOT_RETENTION_DAYS = 90

    def _record_snapshots(self) -> None:
        """Persist one per-creator-per-day snapshot of view/subscriber totals.

        Called after a successful fetch (alongside the milestone checks). For
        each creator, today's row is upserted (so re-fetching the same day just
        refreshes the numbers). Rows older than the retention window are pruned.
        ``subscriber_total`` is the max per-platform count (matching the
        milestone logic in :meth:`MainWindow._check_milestones`).
        """
        creators = self.get_creators()
        if not creators:
            return
        view_totals = self.bulk_view_totals()
        sub_counts = self.bulk_subscriber_counts()
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        rows = []
        for c in creators:
            cid = c['id']
            counts = sub_counts.get(cid, {})
            yt = counts.get('youtube', 0)
            tw = counts.get('twitch', 0)
            sub_total = max(yt, tw)
            view_total = view_totals.get(cid, 0)
            rows.append((cid, today, view_total, sub_total))
        upsert_sql = (
            'INSERT INTO creator_snapshots (creator_id, captured_at, view_total, subscriber_total) '
            'VALUES (?, ?, ?, ?) '
            'ON CONFLICT(creator_id, captured_at) DO UPDATE SET '
            'view_total = excluded.view_total, subscriber_total = excluded.subscriber_total'
        )
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self._SNAPSHOT_RETENTION_DAYS)).strftime('%Y-%m-%d')
        with self._write_lock:
            try:
                if rows:
                    self._conn.executemany(upsert_sql, rows)
                self._conn.execute('DELETE FROM creator_snapshots WHERE captured_at < ?', (cutoff,))
                self._conn.commit()
            except sqlite3.Error as exc:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
                raise ValueError(f'Database error: {exc}') from exc
            self._backup_locked()

    def _snapshot_bookends(self, window_days: int) -> tuple[dict[int, int], dict[int, int]]:
        """Return ``(latest, baseline)`` subscriber_total maps in two queries.

        Shared by :meth:`bulk_trend_arrows` and :meth:`check_velocity_alerts`
        so the two correlated subqueries aren't re-issued by each caller.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).strftime('%Y-%m-%d')
        latest = {r['creator_id']: r['subscriber_total'] for r in self._read(
            'SELECT creator_id, subscriber_total FROM creator_snapshots s '
            'WHERE captured_at = (SELECT MAX(captured_at) FROM creator_snapshots WHERE creator_id = s.creator_id)'
        )}
        baseline = {r['creator_id']: r['subscriber_total'] for r in self._read(
            'SELECT creator_id, subscriber_total FROM creator_snapshots s '
            'WHERE captured_at = (SELECT MIN(captured_at) FROM creator_snapshots '
            'WHERE creator_id = s.creator_id AND captured_at >= ?)',
            (cutoff,),
        )}
        return latest, baseline

    def bulk_trend_arrows(self, window_days: int = 7) -> dict[int, str]:
        """Return {creator_id: 'up'|'down'|'flat'|'none'} over a snapshot window.

        Compares the most recent subscriber snapshot to the one roughly
        ``window_days`` ago. A change under 1 % is reported as 'flat' so tiny
        fluctuations on large channels don't flip the arrow constantly.
        """
        creators = self.get_creators()
        if not creators:
            return {}
        latest, baseline = self._snapshot_bookends(window_days)
        result: dict[int, str] = {}
        for c in creators:
            cid = c['id']
            cur = latest.get(cid)
            prev = baseline.get(cid)
            if cur is None or prev is None:
                result[cid] = 'none'
                continue
            if prev == 0:
                result[cid] = 'up' if cur > 0 else 'flat'
                continue
            pct = (cur - prev) / prev * 100.0
            if abs(pct) < 1.0:
                result[cid] = 'flat'
            elif pct > 0:
                result[cid] = 'up'
            else:
                result[cid] = 'down'
        return result

    def check_velocity_alerts(self, window_days: int = 3, growth_pct: float = 20.0) -> list[dict[str, Any]]:
        """Detect creators whose subscribers grew ≥ ``growth_pct`` in the window.

        Returns one dict per newly-detected spike: ``{'type': 'velocity_spike',
        'creator_id', 'threshold': window_days, 'pct': actual_pct}``. Dedup is
        on ``(creator_id, 'velocity_spike', window_days)`` so each creator
        notifies at most once per window length (the trend arrow shows ongoing
        state on the card).

        Uses :meth:`existing_alerts` / :meth:`add_alerts` so an N-creator pass
        issues one SELECT and one INSERT instead of N of each.
        """
        creators = self.get_creators()
        if not creators:
            return []
        latest, baseline = self._snapshot_bookends(window_days)
        cids = [c['id'] for c in creators]
        existing = self.existing_alerts(cids, 'velocity_spike')
        alerts: list[dict[str, Any]] = []
        new_rows: list[tuple[int, str, int]] = []
        for c in creators:
            cid = c['id']
            cur = latest.get(cid)
            prev = baseline.get(cid)
            if cur is None or prev is None or prev == 0:
                continue
            pct = (cur - prev) / prev * 100.0
            if pct >= growth_pct and (cid, window_days) not in existing:
                alerts.append({'type': 'velocity_spike', 'creator_id': cid, 'threshold': window_days, 'pct': round(pct, 1)})
                new_rows.append((cid, 'velocity_spike', window_days))
        self.add_alerts(new_rows)
        return alerts

    def check_inactivity_alerts(self, idle_days: int = 30) -> list[dict[str, Any]]:
        """Detect creators with no upload in the last ``idle_days`` days.

        Returns one dict per newly-idle creator: ``{'type': 'inactivity',
        'creator_id', 'threshold': idle_days, 'idle_days': actual}``. Dedup is
        on ``(creator_id, 'inactivity', idle_days)``.
        """
        creators = self.get_creators()
        last_activity = self.bulk_last_activity()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=idle_days)).strftime('%Y-%m-%dT%H:%M:%SZ')
        cids = [c['id'] for c in creators]
        existing = self.existing_alerts(cids, 'inactivity')
        alerts: list[dict[str, Any]] = []
        new_rows: list[tuple[int, str, int]] = []
        for c in creators:
            cid = c['id']
            last = last_activity.get(cid, '')
            if not last:
                # Never uploaded — only count as inactive if they've been a
                # member long enough to have produced something.
                continue
            if last < cutoff and (cid, idle_days) not in existing:
                # Days since last upload (best-effort from the ISO date).
                try:
                    last_dt = datetime.fromisoformat(last.replace('Z', '+00:00'))
                    delta = (datetime.now(timezone.utc) - last_dt).days
                except (ValueError, TypeError):
                    delta = idle_days
                alerts.append({'type': 'inactivity', 'creator_id': cid, 'threshold': idle_days, 'idle_days': delta})
                new_rows.append((cid, 'inactivity', idle_days))
        self.add_alerts(new_rows)
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
        # Precompute the cutoff as an ISO string so the filter on upload_date is
        # a plain string comparison (sargable) rather than a julianday() call on
        # every row, which would defeat any index.  upload_date is stored as an
        # ISO-8601 string, so lexicographic comparison matches chronological order.
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')
        rows = self._read(
            'SELECT creator_id, '
            '  CAST((julianday(\'now\') - julianday(upload_date)) / 7 AS INTEGER) AS week_offset, '
            '  COUNT(*) AS cnt '
            'FROM media_content '
            'WHERE upload_date != \'\' AND upload_date > ? '
            'GROUP BY creator_id, week_offset '
            'ORDER BY creator_id, week_offset',
            (cutoff,)
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
            # Build every row up front, then commit in one transaction so an
            # import of N creators/media doesn't issue N separate commits.
            role_rows = [(r['id'], r['role_name'], r['role_color']) for r in data.get('roles', [])]
            creator_rows = []
            for c in data.get('creators', []):
                platforms = c.get('platforms', [])
                if isinstance(platforms, list):
                    platforms = json.dumps(platforms)
                tags_json = json.dumps(c.get('tags', [])) if isinstance(c.get('tags'), list) else (c.get('tags') or '[]')
                creator_rows.append((
                    c['id'], c['nickname'], platforms, c.get('role_id'),
                    c.get('youtube_type'), c.get('youtube_channel_id'),
                    c.get('youtube_link'), c.get('twitch_link'),
                    _constrain_cache_path(c.get('pfp_url', '')),
                    c.get('date_added'), c.get('is_new_activity', 0),
                    c.get('notes', ''), tags_json,
                ))
            media_rows = []
            for m in data.get('media_content', []):
                media_rows.append((
                    m['creator_id'], m['platform'], m['content_id'], m.get('title', ''),
                    _constrain_cache_path(m.get('thumbnail_path', '')),
                    _constrain_cache_path(m.get('thumbnail_url', '')),
                    m.get('upload_date', ''), m.get('view_count', 0),
                    m.get('is_verified', 0), m.get('is_short', 0),
                    m.get('is_stream', 0), m.get('description', ''),
                    m.get('type_override'),
                ))
            setting_rows = []
            for s in data.get('settings', []):
                key = s.get('key', '')
                if key in ('current_profile', 'api_keys_json'):
                    continue
                setting_rows.append((key, s.get('value', '')))
            with self._write_lock:
                try:
                    if role_rows:
                        self._conn.executemany(
                            'INSERT INTO roles (id, role_name, role_color) VALUES (?, ?, ?)',
                            role_rows,
                        )
                    if creator_rows:
                        self._conn.executemany(
                            'INSERT INTO creators (id, nickname, platforms, role_id, youtube_type, '
                            'youtube_channel_id, youtube_link, twitch_link, pfp_url, date_added, is_new_activity, notes, tags) '
                            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            creator_rows,
                        )
                    if media_rows:
                        self._conn.executemany(
                            'INSERT INTO media_content (creator_id, platform, content_id, title, '
                            'thumbnail_path, thumbnail_url, upload_date, view_count, is_verified, '
                            'is_short, is_stream, description, type_override) '
                            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            media_rows,
                        )
                    if setting_rows:
                        self._conn.executemany(
                            'INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
                            setting_rows,
                        )
                    self._conn.commit()
                except sqlite3.Error as exc:
                    try:
                        self._conn.rollback()
                    except Exception:
                        pass
                    raise ValueError(f'Database error: {exc}') from exc
                self._backup_locked()
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
            pfp_url=_constrain_cache_path(c.get('pfp_url')),
            notes=c.get('notes', ''),
            tags=c.get('tags') if isinstance(c.get('tags'), list) else None,
        )
        # Import media content in one transaction (avoids a commit per video).
        media_rows = []
        for m in data.get('media_content', []):
            media_rows.append((
                new_id, m['platform'], m['content_id'], m.get('title', ''),
                _constrain_cache_path(m.get('thumbnail_path', '')),
                _constrain_cache_path(m.get('thumbnail_url', '')),
                m.get('upload_date', ''), m.get('view_count', 0),
                int(bool(m.get('is_verified', 0))), int(bool(m.get('is_short', 0))),
                int(bool(m.get('is_stream', 0))), m.get('description', ''),
                m.get('type_override'),
            ))
        if media_rows:
            with self._write_lock:
                try:
                    self._conn.executemany(
                        'INSERT INTO media_content (creator_id, platform, content_id, title, '
                        'thumbnail_path, thumbnail_url, upload_date, view_count, is_verified, '
                        'is_short, is_stream, description, type_override) '
                        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        media_rows,
                    )
                    self._conn.commit()
                except sqlite3.Error as exc:
                    try:
                        self._conn.rollback()
                    except Exception:
                        pass
                    raise ValueError(f'Database error: {exc}') from exc
                self._backup_locked()
        # Import stats
        stats = data.get('stats', {})
        if 'youtube_subscribers' in stats:
            self.set_setting(f'yt_channel_subscribers_{new_id}', str(stats['youtube_subscribers']))
        if 'youtube_views' in stats:
            self.set_setting(f'yt_channel_views_{new_id}', str(stats['youtube_views']))
        if 'twitch_followers' in stats:
            self.set_setting(f'twitch_followers_{new_id}', str(stats['twitch_followers']))
        return new_id

    # ── Discover / Market Research ────────────────────────────────────
    # All Discover data is per-profile and isolated from the tracked
    # roster.  ``search_cache`` stores raw API results keyed by a hash of
    # the query params so re-running the same search costs 0 quota units.
    # ``discovered_creators`` holds scored channels.  ``candidate_pool``
    # is the flagged subset with outreach notes.  ``ai_evaluations`` is a
    # log of on-demand AI verdicts per channel.

    def get_cached_search(self, query_hash: str) -> dict[str, Any] | None:
        """Return a cached search result by query hash, or None."""
        rows = self._read(
            'SELECT id, params_json, results_json, created_at '
            'FROM search_cache WHERE query_hash = ? ORDER BY id DESC LIMIT 1',
            (query_hash,),
        )
        if rows:
            row = rows[0]
            try:
                row['results'] = json.loads(row['results_json'])
                row['params'] = json.loads(row['params_json'])
            except (json.JSONDecodeError, TypeError):
                return None
            return row
        return None

    def save_cached_search(self, query_hash: str, params_json: str, results_json: str) -> None:
        """Persist a search result so re-running the same query is free."""
        self._write(
            'INSERT INTO search_cache (query_hash, params_json, results_json) VALUES (?, ?, ?)',
            (query_hash, params_json, results_json),
        )

    def list_cached_searches(self) -> list[dict[str, Any]]:
        """Return a summary of cached searches (id, created_at).

        Deliberately omits the ``results_json`` blob — callers (the cache
        status label in Settings/Discover) only need the count and the
        timestamps, so loading the full JSON payload for every cached
        search would be wasted work as the cache grows.
        """
        return self._read(
            'SELECT id, created_at FROM search_cache ORDER BY id DESC'
        )

    def count_cached_searches(self) -> int:
        """Return the number of cached searches (cheap COUNT, no payload)."""
        rows = self._read('SELECT COUNT(*) AS n FROM search_cache')
        return int(rows[0]['n']) if rows else 0

    def is_candidate_flagged(self, channel_id: str) -> bool:
        """Cheap EXISTS check for one channel's flag state.

        Used per flag-toggle instead of loading the full candidate pool
        (which joins discovered_creators) just to test membership.
        """
        if not channel_id:
            return False
        rows = self._read(
            'SELECT 1 FROM candidate_pool WHERE channel_id = ? LIMIT 1',
            (channel_id,),
        )
        return bool(rows)

    def tracked_channel_ids(self) -> set[str]:
        """Return the set of YouTube channel IDs already on the roster.

        Shared by the discover workers so they don't each re-implement the
        loop over ``get_creators()``.
        """
        ids: set[str] = set()
        for c in self.get_creators():
            cid = c.get('youtube_channel_id')
            if cid:
                ids.add(cid)
        return ids

    def clear_discover_cache(self) -> int:
        """Delete all cached search results.  Returns the number deleted.

        Flagged candidates (candidate_pool) and their discovered_creators
        rows are preserved so outreach notes survive a cache clear.
        """
        cur = self._write('DELETE FROM search_cache')
        # Also drop discovered_creators that are NOT flagged — flagged ones
        # are kept because candidate_pool references them via FK.
        self._write(
            'DELETE FROM discovered_creators WHERE channel_id NOT IN '
            '(SELECT channel_id FROM candidate_pool)'
        )
        return cur.rowcount

    def upsert_discovered_creator(self, data: dict[str, Any]) -> None:
        """Insert or update a discovered channel by channel_id.

        Preserves flagged/notes state in candidate_pool (joined by
        channel_id) and does not touch first_discovered_at on update.
        """
        cols = (
            'channel_id, handle, title, pfp_url, subscriber_count, view_count, '
            'video_count, cadence_per_week, growth_signal, engagement, niche_fit, '
            'views_per_sub, potential_score, recent_titles_json, is_short_channel, '
            'last_refreshed_at'
        )
        placeholders = '?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?'
        vals = (
            data['channel_id'], data.get('handle', ''), data.get('title', ''),
            data.get('pfp_url', ''), int(data.get('subscriber_count', 0)),
            int(data.get('view_count', 0)), int(data.get('video_count', 0)),
            float(data.get('cadence_per_week', 0.0)), float(data.get('growth_signal', 0.0)),
            float(data.get('engagement', 0.0)), float(data.get('niche_fit', 0.0)),
            float(data.get('views_per_sub', 0.0)), int(data.get('potential_score', 0)),
            json.dumps(data.get('recent_titles', [])), int(data.get('is_short_channel', 0)),
            data.get('last_refreshed_at', ''),
        )
        self._write(
            f'INSERT INTO discovered_creators ({cols}) VALUES ({placeholders}) '
            'ON CONFLICT(channel_id) DO UPDATE SET '
            'handle=excluded.handle, title=excluded.title, pfp_url=excluded.pfp_url, '
            'subscriber_count=excluded.subscriber_count, view_count=excluded.view_count, '
            'video_count=excluded.video_count, cadence_per_week=excluded.cadence_per_week, '
            'growth_signal=excluded.growth_signal, engagement=excluded.engagement, '
            'niche_fit=excluded.niche_fit, views_per_sub=excluded.views_per_sub, '
            'potential_score=excluded.potential_score, '
            'recent_titles_json=excluded.recent_titles_json, '
            'is_short_channel=excluded.is_short_channel, '
            'last_refreshed_at=excluded.last_refreshed_at',
            vals,
        )

    def get_discovered_creators(self, sort: str = 'potential', limit: int | None = None) -> list[dict[str, Any]]:
        """Return discovered creators, sorted.  Joins candidate_pool to
        expose is_flagged + notes for the UI without a second query."""
        order = {
            'potential': 'potential_score DESC',
            'views_per_sub': 'views_per_sub DESC',
            'subscribers': 'subscriber_count ASC',
            'views': 'view_count DESC',
            'cadence': 'cadence_per_week DESC',
        }.get(sort, 'potential_score DESC')
        sql = (
            'SELECT d.*, '
            'CASE WHEN c.channel_id IS NOT NULL THEN 1 ELSE 0 END AS is_flagged, '
            'COALESCE(c.notes, \'\') AS notes '
            'FROM discovered_creators d '
            'LEFT JOIN candidate_pool c ON c.channel_id = d.channel_id '
            f'ORDER BY {order}'
        )
        rows = self._read(sql)
        for r in rows:
            try:
                r['recent_titles'] = json.loads(r.get('recent_titles_json', '[]'))
            except (json.JSONDecodeError, TypeError):
                r['recent_titles'] = []
            r['is_short_channel'] = bool(r.get('is_short_channel', 0))
            r['is_flagged'] = bool(r.get('is_flagged', 0))
        if limit is not None:
            rows = rows[:limit]
        return rows

    def get_discovered_creator(self, channel_id: str) -> dict[str, Any] | None:
        rows = self._read(
            'SELECT * FROM discovered_creators WHERE channel_id = ?', (channel_id,)
        )
        if rows:
            r = rows[0]
            try:
                r['recent_titles'] = json.loads(r.get('recent_titles_json', '[]'))
            except (json.JSONDecodeError, TypeError):
                r['recent_titles'] = []
            r['is_short_channel'] = bool(r.get('is_short_channel', 0))
            return r
        return None

    def flag_candidate(self, channel_id: str, notes: str = '') -> None:
        """Add a discovered creator to the flagged candidate pool."""
        self._write(
            'INSERT INTO candidate_pool (channel_id, notes, last_updated_at) '
            'VALUES (?, ?, ?) '
            'ON CONFLICT(channel_id) DO UPDATE SET notes = excluded.notes, '
            'last_updated_at = excluded.last_updated_at',
            (channel_id, notes, _utc_now()),
        )

    def unflag_candidate(self, channel_id: str) -> None:
        self._write('DELETE FROM candidate_pool WHERE channel_id = ?', (channel_id,))

    def set_candidate_notes(self, channel_id: str, notes: str) -> None:
        self._write(
            'UPDATE candidate_pool SET notes = ?, last_updated_at = ? WHERE channel_id = ?',
            (notes, _utc_now(), channel_id),
        )

    def get_candidate_pool(self) -> list[dict[str, Any]]:
        """Return flagged candidates joined with their discovered-creator stats."""
        rows = self._read(
            'SELECT d.channel_id, d.handle, d.title, d.pfp_url, d.subscriber_count, '
            'd.view_count, d.views_per_sub, d.potential_score, d.cadence_per_week, '
            'c.notes, c.flagged_at, c.last_updated_at '
            'FROM candidate_pool c '
            'JOIN discovered_creators d ON d.channel_id = c.channel_id '
            'ORDER BY c.flagged_at DESC'
        )
        return rows

    def get_candidate_count(self) -> int:
        rows = self._read('SELECT COUNT(*) AS n FROM candidate_pool')
        return int(rows[0]['n']) if rows else 0

    def save_ai_evaluation(self, channel_id: str, provider: str, model: str, verdict: str, rationale: str) -> None:
        self._write(
            'INSERT INTO ai_evaluations (channel_id, provider, model, verdict, rationale) '
            'VALUES (?, ?, ?, ?, ?)',
            (channel_id, provider, model, verdict, rationale),
        )

    def get_latest_ai_evaluation(self, channel_id: str) -> dict[str, Any] | None:
        rows = self._read(
            'SELECT provider, model, verdict, rationale, created_at '
            'FROM ai_evaluations WHERE channel_id = ? '
            'ORDER BY id DESC LIMIT 1',
            (channel_id,),
        )
        return rows[0] if rows else None

    def promote_candidate_to_roster(self, channel_id: str, role_id: int) -> int | None:
        """Promote a discovered creator into the tracked roster.

        Inserts a creators row with the discovered channel's YouTube link
        and PFP, then removes the candidate_pool entry (keeping the
        discovered_creators row for history).  Returns the new creator id,
        or None if the channel is unknown.
        """
        d = self.get_discovered_creator(channel_id)
        if not d:
            return None
        # resolve_channels stores the YouTube customUrl with its leading '@'
        # intact, so strip any '@' prefix before re-adding exactly one.
        handle = (d.get('handle', '') or '').lstrip('@')
        # Guard against re-promoting a channel already on the roster —
        # creators.youtube_channel_id has no UNIQUE constraint, so an
        # unconditional insert would duplicate the member.
        existing = self._read(
            'SELECT id FROM creators WHERE youtube_channel_id = ? LIMIT 1',
            (channel_id,),
        )
        if existing:
            self.unflag_candidate(channel_id)
            return int(existing[0]['id'])
        nickname = d.get('title', '') or handle or channel_id
        yt_link = f'https://www.youtube.com/{("@" + handle) if handle else "channel/" + channel_id}'
        new_id = self.add_creator(
            nickname=nickname, role_id=role_id, platforms=['youtube'],
            youtube_channel_id=channel_id, youtube_link=yt_link,
            pfp_url=d.get('pfp_url') or None,
            notes=f'Promoted from Discover. Potential score: {d.get("potential_score", 0)}.',
        )
        # Stash discovered stats so the new roster member's first refresh
        # has a baseline, mirroring creator import behaviour.
        self.set_setting(f'yt_channel_subscribers_{new_id}', str(d.get('subscriber_count', 0)))
        self.set_setting(f'yt_channel_views_{new_id}', str(d.get('view_count', 0)))
        # Remove from the flagged pool so it stops appearing as a candidate.
        self.unflag_candidate(channel_id)
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