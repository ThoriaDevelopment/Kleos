"""Thumbnail image caching for Kleos.

Downloads remote thumbnails to a local cache directory using URL-based
hashed filenames. Survives manual cache-folder deletion at runtime by
auto-recreating directories and re-downloading missing files.

Uses per-URL locks to prevent concurrent downloads of the same thumbnail
from racing on the temporary file, which caused PermissionError on Windows.
"""
from __future__ import annotations
import hashlib
import logging
import re
import threading
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
import requests
from .paths import THUMBNAILS_DIR
logger = logging.getLogger(__name__)
_REQUEST_TIMEOUT = 15
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

def _release_download_lock(key: str) -> None:
    """Remove a download lock from the dict after use to prevent unbounded growth."""
    with _download_locks_lock:
        _download_locks.pop(key, None)


def ensure_thumbnail(url: str) -> Optional[str]:
    """Download *url* to the local cache if missing, then return its path.

    Returns the local file path on success, or ``None`` on download failure.
    Safe to call when the cache directory has been deleted mid-run — the
    directory is re-created automatically and the image re-downloaded.

    Uses a per-URL lock so that concurrent threads downloading the same
    thumbnail don't race on the temporary file.
    """
    if not url:
        return None
    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    local = THUMBNAILS_DIR / _url_to_filename(url)
    if local.exists() and local.stat().st_size > 0:
        return str(local)
    lock = _get_download_lock(url)
    try:
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
                logger.warning('Thumbnail download failed for %s: %s', url, exc)
                try:
                    tmp = local.with_suffix(local.suffix + '.tmp')
                    if tmp.exists():
                        tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                return None
    finally:
        _release_download_lock(url)


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
    try:
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
    finally:
        _release_download_lock(lock_key)


def prune_cache(max_files: int = 500) -> int:
    """Delete oldest cached thumbnails when the cache exceeds *max_files*.

    Only prunes hash-named thumbnail files (``<16-hex-chars>.<ext>``).
    PFP files (named ``<nickname>_<id>.<ext>``) are kept because they are
    expensive to re-download and are not redundant content.

    Returns the number of files removed.
    """
    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    _hash_pattern = re.compile(r'^[0-9a-f]{16}\.\w+$')
    hash_files = [f for f in THUMBNAILS_DIR.iterdir() if f.is_file() and _hash_pattern.match(f.name)]
    if len(hash_files) <= max_files:
        return 0
    def _safe_mtime(f):
        try:
            return f.stat().st_mtime
        except (FileNotFoundError, OSError):
            return float('inf')

    hash_files.sort(key=_safe_mtime)
    to_remove = hash_files[:len(hash_files) - max_files]
    for f in to_remove:
        f.unlink(missing_ok=True)
    return len(to_remove)


def refresh_thumbnails_high_quality(db: Any) -> int:
    """Re-fetch all thumbnails from their original URLs, overwriting cached versions.

    Iterates all media_content rows, deletes the cached file for each thumbnail
    URL, and re-downloads from the source.  Updates ``thumbnail_path`` in the
    database for every successfully refreshed thumbnail.

    Returns the number of thumbnails successfully refreshed.
    """
    refreshed = 0
    media = db.get_media()
    for m in media:
        url = m.get('thumbnail_url', '') or ''
        if not url:
            continue
        # Delete the existing cached file so ensure_thumbnail re-downloads
        local_path = THUMBNAILS_DIR / _url_to_filename(url)
        if local_path.exists():
            try:
                local_path.unlink()
            except OSError:
                pass
        new_path = ensure_thumbnail(url)
        if new_path:
            db._write(
                'UPDATE media_content SET thumbnail_path = ? WHERE id = ?',
                (new_path, m['id']),
            )
            refreshed += 1
    return refreshed