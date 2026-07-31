"""Thumbnail image caching for Kleos.

Downloads remote thumbnails to a local cache directory using URL-based
hashed filenames. Survives manual cache-folder deletion at runtime by
auto-recreating directories and re-downloading missing files.

Uses per-URL locks to prevent concurrent downloads of the same thumbnail
from racing on the temporary file, which caused PermissionError on Windows.

Thumbnails are pre-scaled to 320×180 (2× display size for HiDPI) at
download time to reduce disk usage and memory consumption.
"""
from __future__ import annotations
import hashlib
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
import requests
from .paths import THUMBNAILS_DIR
logger = logging.getLogger(__name__)
_REQUEST_TIMEOUT = 15
# Pre-scaling dimensions: 2× the display size (160×90) for HiDPI screens.
_THUMB_SCALE_W = 320
_THUMB_SCALE_H = 180
# Per-URL locks prevent concurrent downloads of the same thumbnail.
# Without this, two threads can write to the same .tmp file and race
# on os.replace(), causing PermissionError on Windows.
_download_locks: dict[str, threading.Lock] = {}
_download_locks_lock = threading.Lock()


def _url_to_filename(url: str) -> str:
    """Produce a deterministic filename from a URL: ``<sha256>.<ext>``."""
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    path = urlparse(url).path
    ext = Path(path).suffix.lower() if Path(path).suffix else '.jpg'
    if ext not in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
        ext = '.jpg'
    return f'{h}{ext}'


def get_thumbnail_path(url: str) -> str:
    """Return the local cache path for *url* as a string.

    Does **not** download — only computes the path. Useful when the caller
    just wants to know where the file *would* live.
    """
    return str(THUMBNAILS_DIR / _url_to_filename(url))


def _get_download_lock(url: str) -> threading.Lock:
    """Return a per-URL lock, creating one if necessary."""
    with _download_locks_lock:
        if url not in _download_locks:
            _download_locks[url] = threading.Lock()
        return _download_locks[url]


def _scale_and_save(tmp_path: Path, dest_path: Path) -> bool:
    """Scale the image at *tmp_path* to _THUMB_SCALE_W × _THUMB_SCALE_H
    and save to *dest_path*.

    Uses QImage for scaling since PyQt6 is always available.  Falls back to
    a simple file copy if scaling fails.

    Returns True on success (scaled or copied), False on total failure.
    """
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QImage
        img = QImage(str(tmp_path))
        if img.isNull():
            # Not a valid image — fall back to copying as-is
            os.replace(str(tmp_path), str(dest_path))
            return True
        scaled = img.scaled(
            _THUMB_SCALE_W, _THUMB_SCALE_H,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Determine format from the destination extension
        ext = dest_path.suffix.lower()
        fmt = 'PNG' if ext == '.png' else 'JPG'
        if scaled.save(str(dest_path), fmt, quality=85):
            # Successfully saved scaled image; remove the temp file
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return True
        else:
            # Save failed — fall back to moving the original
            os.replace(str(tmp_path), str(dest_path))
            return True
    except ImportError:
        # PyQt6 not available (shouldn't happen in the app, but be safe)
        os.replace(str(tmp_path), str(dest_path))
        return True
    except Exception as exc:
        logger.warning('Thumbnail scaling failed, using original: %s', exc)
        try:
            os.replace(str(tmp_path), str(dest_path))
            return True
        except OSError:
            return False


def ensure_thumbnail(url: str, *, force: bool = False) -> Optional[str]:
    """Download *url* to the local cache if missing, then return its path.

    The downloaded thumbnail is pre-scaled to 320×180 to reduce disk usage
    and memory consumption.  Returns the local file path on success, or
    ``None`` on download failure.

    Safe to call when the cache directory has been deleted mid-run — the
    directory is re-created automatically and the image re-downloaded.

    Uses a per-URL lock so that concurrent threads downloading the same
    thumbnail don't race on the temporary file.

    When *force* is True, skips the cache-exists check and always
    re-downloads the thumbnail (used for high-quality refresh).  Forced
    downloads are NOT scaled to preserve original quality.
    """
    if not url:
        return None
    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    local = THUMBNAILS_DIR / _url_to_filename(url)
    if not force and local.exists() and local.stat().st_size > 0:
        return str(local)
    lock = _get_download_lock(url)
    with lock:
        # Re-check after acquiring lock — another thread may have downloaded it
        if not force and local.exists() and local.stat().st_size > 0:
            return str(local)
        try:
            with requests.get(url, timeout=_REQUEST_TIMEOUT, stream=True) as resp:
                resp.raise_for_status()
                tmp = local.with_suffix(local.suffix + '.tmp')
                with open(tmp, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
            if force:
                # High-quality refresh: keep original resolution
                tmp.replace(local)
            else:
                # Normal download: scale to display size
                _scale_and_save(tmp, local)
            return str(local)
        except (requests.RequestException, OSError) as exc:
            logger.warning('Thumbnail download failed for %s: %s', url, exc)
            try:
                tmp = local.with_suffix(local.suffix + '.tmp')
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return None


def _sanitize_filename(name: str) -> str:
    """Return *name* with non-filename-safe characters replaced."""
    return ''.join((c if c.isalnum() or c in ['_', '-', '.'] else '_' for c in name))


def ensure_pfp(url: str, nickname: str, creator_id: int | None = None) -> Optional[str]:
    """Download a profile picture to ``cache/thumbnails/<nickname>_<id>.<ext>``.

    Includes the creator ID in the filename to prevent same-nickname creators
    from overwriting each other's cached profile pictures.

    Returns the local file path on success, or ``None`` on failure.
    """
    if not url:
        return None
    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(urlparse(url).path).suffix.lower()
    if ext not in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
        ext = '.jpg'
    safe_name = _sanitize_filename(nickname)
    if creator_id is not None:
        local = THUMBNAILS_DIR / f'{safe_name}_{creator_id}{ext}'
    else:
        local = THUMBNAILS_DIR / f'{safe_name}{ext}'
    if local.exists() and local.stat().st_size > 0:
        return str(local)
    lock_key = str(local)  # Lock by destination path, not URL, to prevent races on same file
    lock = _get_download_lock(lock_key)
    with lock:
        # Re-check after acquiring lock — another thread may have downloaded it
        if local.exists() and local.stat().st_size > 0:
            return str(local)
        try:
            with requests.get(url, timeout=_REQUEST_TIMEOUT, stream=True) as resp:
                resp.raise_for_status()
                tmp = local.with_suffix(local.suffix + '.tmp')
                with open(tmp, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                tmp.replace(local)
            return str(local)
        except (requests.RequestException, OSError) as exc:
            logger.warning('PFP download failed for %s: %s', url, exc)
            try:
                tmp = local.with_suffix(local.suffix + '.tmp')
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return None


def prune_cache(db: Any | None = None, max_orphan_files: int = 200) -> int:
    """Delete cached thumbnails that are no longer referenced in the database.

    Only prunes hash-named thumbnail files (``<16-hex-chars>.<ext>``).
    PFP files (named ``<nickname>_<id>.<ext>``) are always kept.

    When *db* is provided, the function first collects every
    ``thumbnail_path`` stored in the ``media_content`` table and treats
    those files as active.  Only hash-named files that are NOT in this
    active set are considered orphans and eligible for deletion, sorted
    oldest-first.  At most *max_orphan_files* orphaned files are kept;
    any excess is removed.

    When *db* is ``None``, falls back to a simple size-based cap of
    5 000 files so that callers without a database reference still get
    reasonable pruning.

    Returns the number of files removed.
    """
    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    _hash_pattern = re.compile(r'^[0-9a-f]{16}\.\w+$')
    hash_files = [f for f in THUMBNAILS_DIR.iterdir() if f.is_file() and _hash_pattern.match(f.name)]

    def _safe_mtime(f: Path) -> float:
        try:
            return f.stat().st_mtime
        except (FileNotFoundError, OSError):
            return float('inf')

    if db is not None:
        # Database-aware pruning: only delete thumbnails that are no
        # longer referenced by any media_content row.  Active thumbnails
        # (those still in use) are never touched.
        active_paths: set[str] = set()
        for path in db.get_all_thumbnail_paths():
            active_paths.add(str(Path(path)))

        orphans = [f for f in hash_files if str(f) not in active_paths]
        if len(orphans) <= max_orphan_files:
            return 0
        orphans.sort(key=_safe_mtime)
        to_remove = orphans[:len(orphans) - max_orphan_files]
        for f in to_remove:
            f.unlink(missing_ok=True)
        return len(to_remove)
    else:
        # Fallback: simple size-based cap for callers without a DB.
        simple_cap = 5000
        if len(hash_files) <= simple_cap:
            return 0
        hash_files.sort(key=_safe_mtime)
        to_remove = hash_files[:len(hash_files) - simple_cap]
        for f in to_remove:
            f.unlink(missing_ok=True)
        return len(to_remove)


def clear_untracked_thumbnails(db: Any) -> int:
    """Delete cached image files not referenced by ANY profile's database.

    The thumbnail cache (THUMBNAILS_DIR) is shared across all profiles, so a
    file is only safe to remove when no profile references it — either as a
    creator's ``pfp_url`` or a ``media_content.thumbnail_path``.  Files that
    are still tracked by another profile are kept.

    In-progress downloads (``*.tmp``) and non-image files are left untouched.
    Returns the number of files removed.
    """
    _img_exts = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
    in_use = {str(Path(p)) for p in db.get_all_inuse_thumbnail_paths()}
    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    removed = 0
    for f in THUMBNAILS_DIR.iterdir():
        if not f.is_file():
            continue
        suffix = f.suffix.lower()
        if suffix == '.tmp' or suffix not in _img_exts:
            continue
        if str(f) in in_use:
            continue
        try:
            f.unlink(missing_ok=True)
            removed += 1
        except OSError as exc:
            logger.warning('Failed to delete orphan thumbnail %s: %s', f, exc)
    return removed