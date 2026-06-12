from __future__ import annotations
import json
import logging
import os
import re
import threading
import time
from typing import Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from .cache_manager import ensure_pfp, ensure_thumbnail, get_thumbnail_path, prune_cache
from .db_manager import DatabaseManager
logger = logging.getLogger(__name__)
YT_SEARCH_URL = 'https://www.googleapis.com/youtube/v3/search'
YT_VIDEOS_URL = 'https://www.googleapis.com/youtube/v3/videos'
YT_CHANNELS_URL = 'https://www.googleapis.com/youtube/v3/channels'
YT_PLAYLIST_ITEMS_URL = 'https://www.googleapis.com/youtube/v3/playlistItems'
TWITCH_AUTH_URL = 'https://id.twitch.tv/oauth2/token'
TWITCH_STREAMS_URL = 'https://api.twitch.tv/helix/streams'
TWITCH_USERS_URL = 'https://api.twitch.tv/helix/users'
TWITCH_VIDEOS_URL = 'https://api.twitch.tv/helix/videos'
_REQUEST_TIMEOUT = 15
_COOLDOWN_SECONDS = 30
_RETRY_ADAPTER = HTTPAdapter(max_retries=Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=['GET', 'POST', 'HEAD'],
    raise_on_status=False,
))
def _diag_response(resp: requests.Response, context: str) -> None:
    """Log the response body when the API returns a non-200 status.\n\nCatches common Google API error reasons like API_NOT_ENABLED\nand ACCESS_NOT_CONFIGURED and logs the full JSON error so the\ndeveloper can diagnose credential or quota problems.\n"""
    if resp.status_code == 200:
        return None
    else:
        body = resp.text[:2000]
        logger.warning('%s — HTTP %d %s: %s', context, resp.status_code, resp.reason, body[:500])
        resp.raise_for_status()
class YouTubeVideo:
    __slots__ = ('content_id', 'title', 'thumbnail_url', 'upload_date', 'view_count', 'is_short', 'description')
    def __init__(self, content_id: str, title: str, thumbnail_url: str, upload_date: str, view_count: int, is_short: bool, description: str='') -> None:
        self.content_id = content_id
        self.title = title
        self.thumbnail_url = thumbnail_url
        self.upload_date = upload_date
        self.view_count = view_count
        self.is_short = is_short
        self.description = description
    def as_dict(self) -> dict[str, Any]:
        return {s: getattr(self, s) for s in self.__slots__}
class TwitchStream:
    __slots__ = ('content_id', 'title', 'thumbnail_url', 'started_at', 'viewer_count', 'user_login', 'description')
    def __init__(self, content_id: str, title: str, thumbnail_url: str, started_at: str, viewer_count: int, user_login: str, description: str='') -> None:
        self.content_id = content_id
        self.title = title
        self.thumbnail_url = thumbnail_url
        self.started_at = started_at
        self.viewer_count = viewer_count
        self.user_login = user_login
        self.description = description
    def as_dict(self) -> dict[str, Any]:
        return {s: getattr(self, s) for s in self.__slots__}
class YouTubeClient:
    """Fetches the latest uploads for a given channel ID via YouTube v3."""
    def __init__(self, api_key: str) -> None:
        self._key = api_key
        self._session = requests.Session()
        self._session.mount('https://', _RETRY_ADAPTER)
        self._session.mount('http://', _RETRY_ADAPTER)
    def fetch_latest(self, channel_id: str, *, uploads_playlist_id: str | None = None, cancel_check=None, max_videos: int | None = None) -> tuple[list[YouTubeVideo], bool]:
        """Return videos for *channel_id* via paginated playlistItems.

        Uses the channel's uploads playlist (``UU…``) instead of the
        restricted ``/search`` endpoint.  If *uploads_playlist_id* is
        provided it is used directly; otherwise it is derived from
        *channel_id* by replacing the ``UC`` prefix with ``UU``.

        Paginates through pages using ``nextPageToken``.  If *max_videos*
        is set, stops once that many videos have been collected.
        If *max_videos* is None (default), fetches all videos.

        *cancel_check* is an optional callable that returns True when
        the fetch should be aborted between pages.

        Returns ``(videos, complete)`` where *complete* is True only if
        every page was fetched without error or early cancellation.
        On partial failure, returns whatever videos were collected so far
        with *complete* set to False — callers can save this partial data
        instead of losing everything.
        """
        playlist_id = uploads_playlist_id
        if not playlist_id:
            if channel_id.startswith('UC'):
                playlist_id = 'UU' + channel_id[2:]
            else:
                logger.warning("Cannot derive uploads playlist from '%s'", channel_id)
                return [], False
        all_videos = []
        complete = True
        next_page_token = None
        while True:
            if cancel_check and cancel_check():
                complete = False
                break
            params = {
                'key': self._key,
                'playlistId': playlist_id,
                'part': 'snippet',
                'maxResults': '50',
            }
            if next_page_token:
                params['pageToken'] = next_page_token
            try:
                resp = self._session.get(YT_PLAYLIST_ITEMS_URL, params=params, timeout=_REQUEST_TIMEOUT)
                _diag_response(resp, f'YouTube playlistItems playlist={playlist_id} page={next_page_token!r}')
            except requests.RequestException as exc:
                logger.warning('YouTube playlistItems page fetch failed for %s: %s', channel_id, exc)
                complete = False
                break
            try:
                data = resp.json()
            except (ValueError, json.JSONDecodeError):
                logger.warning('YouTube playlistItems returned invalid JSON for %s', channel_id)
                complete = False
                break
            items = data.get('items', [])
            video_ids = []
            for it in items:
                rid = it.get('snippet', {}).get('resourceId', {})
                vid = rid.get('videoId')
                if vid:
                    video_ids.append(vid)
            stats = self._fetch_stats(video_ids) if video_ids else {}
            for item in items:
                rid = item.get('snippet', {}).get('resourceId', {})
                vid = rid.get('videoId')
                if not vid:
                    continue
                snip = item['snippet']
                thumb = snip.get('thumbnails', {}).get('high', snip.get('thumbnails', {}).get('medium', snip.get('thumbnails', {}).get('default', {}))).get('url', '')
                stat = stats.get(vid, {})
                raw_views = stat.get('viewCount', 0) or 0
                try:
                    video_views = int(raw_views)
                except (ValueError, TypeError):
                    video_views = 0
                all_videos.append(YouTubeVideo(content_id=vid, title=snip.get('title', ''), thumbnail_url=thumb, upload_date=snip.get('publishedAt', ''), view_count=video_views, is_short=stat.get('is_short', False), description=snip.get('description', '')))
            if max_videos is not None and len(all_videos) >= max_videos:
                all_videos = all_videos[:max_videos]
                break
            next_page_token = data.get('nextPageToken')
            if not next_page_token:
                break
        return all_videos, complete
    def _fetch_stats(self, video_ids: list[str]) -> dict[str, dict]:
        """Batch-fetch view counts, duration, and content details.

        Returns an empty dict on failure so that partial page data can
        still be saved — videos will just lack view counts and short
        detection until the next refresh.
        """
        if not video_ids:
            return {}
        result = {}
        # YouTube API limits to 50 IDs per request, so chunk if needed.
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i:i + 50]
            try:
                params = {'key': self._key, 'id': ','.join(chunk), 'part': 'statistics,contentDetails'}
                resp = self._session.get(YT_VIDEOS_URL, params=params, timeout=_REQUEST_TIMEOUT)
                _diag_response(resp, 'YouTube video stats')
                try:
                    data = resp.json()
                except (ValueError, json.JSONDecodeError):
                    logger.warning('YouTube video stats returned invalid JSON')
                    continue
                for v in data.get('items', []):
                    info = v.get('statistics', {})
                    cd = v.get('contentDetails', {})
                    duration = cd.get('duration', '')
                    info['is_short'] = self._is_short_duration(duration)
                    result[v['id']] = info
            except requests.RequestException as exc:
                logger.warning('YouTube video stats fetch failed: %s', exc)
        return result
    @staticmethod
    def _is_short_duration(iso_duration: str) -> bool:
        """Return True if an ISO 8601 duration represents 60 seconds or less."""
        if not iso_duration:
            return False
        m = re.match('PT(?:(\\d+)H)?(?:(\\d+)M)?(?:(\\d+(?:\\.\\d+)?)S)?', iso_duration)
        if not m:
            return False
        hours = int(m.group(1) or 0)
        minutes = int(m.group(2) or 0)
        seconds = float(m.group(3) or 0)
        # Unknown/zero duration (e.g. bare "PT") should not be classified as a short
        if hours == 0 and minutes == 0 and seconds == 0:
            return False
        total_seconds = hours * 3600 + minutes * 60 + seconds
        return total_seconds <= 60
    def get_channel_id(self, handle: str) -> str | None:
        """Resolve a ``@handle`` to a channel ID."""
        try:
            params = {'key': self._key, 'part': 'id', 'forHandle': handle.lstrip('@')}
            resp = self._session.get(YT_CHANNELS_URL, params=params, timeout=_REQUEST_TIMEOUT)
            _diag_response(resp, f'YouTube channel resolve handle={handle}')
        except requests.RequestException as exc:
            logger.warning('YouTube channel resolve failed for %s: %s', handle, exc)
            return None
        try:
            items = resp.json().get('items', [])
        except (ValueError, json.JSONDecodeError):
            logger.warning('YouTube channel resolve returned invalid JSON for handle=%s', handle)
            return None
        return items[0]['id'] if items else None
    def fetch_channel_profile(self, identifier: str, *, is_handle: bool=False) -> dict[str, Any] | None:
        """Fetch channel metadata including display name, PFP URL, and stats.\n\nWhen *is_handle* is True, *identifier* is treated as a ``@handle``\nand routed through the ``forHandle`` parameter.  Otherwise it is\ntreated as a channel ID and routed through ``id``.\n\nReturns a dict with keys ``channel_id``, ``display_name``,\n``pfp_url``, ``subscriber_count``, ``view_count``, or ``None``\non failure.\n"""
        params = {'key': self._key, 'part': 'id,snippet,statistics,contentDetails'}
        if is_handle:
            params['forHandle'] = identifier.lstrip('@')
        else:
            params['id'] = identifier
        try:
            resp = self._session.get(YT_CHANNELS_URL, params=params, timeout=_REQUEST_TIMEOUT)
            _diag_response(resp, f'YouTube channel profile id={identifier}')
        except requests.RequestException as exc:
            logger.warning('YouTube channel profile fetch failed: %s', exc)
            return None
        items = resp.json().get('items', [])
        if not items:
            return None
        else:
            item = items[0]
            channel_id = item['id']
            snippet = item.get('snippet', {})
            display_name = snippet.get('title', '')
            thumbnails = snippet.get('thumbnails', {})
            pfp_url = ''
            for key in ['high', 'medium', 'default']:
                thumb = thumbnails.get(key, {})
                if thumb.get('url'):
                    pfp_url = thumb['url']
                    break
            statistics = item.get('statistics', {})
            subscriber_count = 0
            try:
                subscriber_count = int(statistics.get('subscriberCount', 0) or 0)
            except (ValueError, TypeError):
                pass
            view_count = 0
            try:
                view_count = int(statistics.get('viewCount', 0) or 0)
            except (ValueError, TypeError):
                pass
            uploads_playlist_id = None
            content_details = item.get('contentDetails', {})
            related_playlists = content_details.get('relatedPlaylists', {})
            uploads_playlist_id = related_playlists.get('uploads')
            if not uploads_playlist_id and channel_id.startswith('UC'):
                uploads_playlist_id = 'UU' + channel_id[2:]
            return {'channel_id': channel_id, 'display_name': display_name, 'pfp_url': pfp_url, 'subscriber_count': subscriber_count, 'view_count': view_count, 'uploads_playlist_id': uploads_playlist_id}
class TwitchClient:
    """Fetches live/recent streams for a given user login via Twitch Helix."""
    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = requests.Session()
        self._session.mount('https://', _RETRY_ADAPTER)
        self._session.mount('http://', _RETRY_ADAPTER)
        self._token = ''
        self._token_expiry = 0.0
    def _ensure_token(self) -> None:
        if self._token and time.time() < self._token_expiry:
            return
        params = {'client_id': self._client_id, 'client_secret': self._client_secret, 'grant_type': 'client_credentials'}
        resp = self._session.post(TWITCH_AUTH_URL, params=params, timeout=_REQUEST_TIMEOUT)
        _diag_response(resp, 'Twitch auth token')
        try:
            data = resp.json()
        except (ValueError, json.JSONDecodeError):
            logger.warning('Twitch auth returned invalid JSON')
            self._token = ''
            self._token_expiry = 0.0
            raise requests.RequestException('Twitch auth returned invalid JSON')
        token = data.get('access_token')
        if not token or not isinstance(token, str):
            logger.warning('Twitch auth response missing access_token')
            self._token = ''
            self._token_expiry = 0.0
            raise requests.RequestException('Twitch auth response missing access_token')
        else:
            self._token = token
            # Ensure token is valid for at least 60 seconds from now,
            # even if expires_in is very small or negative.
            self._token_expiry = max(time.time() + 60, time.time() + data.get('expires_in', 3600) - 60)
    def _headers(self) -> dict[str, str]:
        self._ensure_token()
        return {'Client-Id': self._client_id, 'Authorization': f'Bearer {self._token}'}
    def fetch_streams(self, user_login: str, first: int = 10) -> list[TwitchStream]:
        """Return recent/live streams for *user_login*, newest first."""
        params = {'user_login': user_login, 'first': str(first)}
        try:
            resp = self._session.get(TWITCH_STREAMS_URL, params=params, headers=self._headers(), timeout=_REQUEST_TIMEOUT)
            _diag_response(resp, f'Twitch streams login={user_login}')
        except requests.RequestException as exc:
            logger.warning('Twitch streams request failed for %s: %s', user_login, exc)
            return []
        try:
            items = resp.json().get('data', [])
        except (ValueError, json.JSONDecodeError):
            logger.warning('Twitch streams returned invalid JSON for %s', user_login)
            return []
        results = []
        for s in items:
            thumb = s.get('thumbnail_url', '').replace('{width}', '446').replace('{height}', '251')
            raw_viewers = s.get('viewer_count', 0) or 0
            try:
                stream_viewers = int(raw_viewers)
            except (ValueError, TypeError):
                stream_viewers = 0
            results.append(TwitchStream(content_id=s['id'], title=s.get('title', ''), thumbnail_url=thumb, started_at=s.get('started_at', ''), viewer_count=stream_viewers, user_login=s.get('user_login', user_login)))
        return results
    def get_user_profile(self, login: str) -> dict[str, Any] | None:
        """Fetch Twitch user profile including PFP URL.

        Returns a dict with keys ``user_id``, ``display_name``,
        ``pfp_url``, ``view_count``, or ``None`` on failure.
        """
        params = {'login': login}
        try:
            resp = self._session.get(TWITCH_USERS_URL, params=params, headers=self._headers(), timeout=_REQUEST_TIMEOUT)
            _diag_response(resp, f'Twitch user profile login={login}')
        except requests.RequestException as exc:
            logger.warning('Twitch user profile fetch failed: %s', exc)
            return None
        try:
            items = resp.json().get('data', [])
        except (ValueError, json.JSONDecodeError):
            logger.warning('Twitch user profile returned invalid JSON for %s', login)
            return None
        if not items:
            return None
        user = items[0]
        raw_views = user.get('view_count', 0) or 0
        try:
            view_count = int(raw_views)
        except (ValueError, TypeError):
            view_count = 0
        return {'user_id': str(user['id']), 'display_name': user.get('display_name', ''), 'pfp_url': user.get('profile_image_url', ''), 'view_count': view_count}

    def fetch_videos(self, user_id: str, cancel_check=None, max_videos: int | None = None) -> tuple[list[TwitchStream], bool]:
        """Return past broadcasts and highlights for *user_id* via Twitch Helix.

        Paginates through pages using cursor-based pagination.  If
        *max_videos* is set, stops once that many videos have been
        collected.  If *max_videos* is None (default), fetches all videos.

        *cancel_check* is an optional callable that returns True when
        the fetch should be aborted between pages.

        Returns ``(videos, complete)`` where *complete* is True only if
        every page was fetched without error or early cancellation.
        """
        all_videos = []
        complete = True
        cursor = None
        while True:
            if cancel_check and cancel_check():
                complete = False
                break
            params = {'user_id': user_id, 'first': '100', 'type': 'all'}
            if cursor:
                params['after'] = cursor
            try:
                resp = self._session.get(TWITCH_VIDEOS_URL, params=params, headers=self._headers(), timeout=_REQUEST_TIMEOUT)
                _diag_response(resp, f'Twitch videos user_id={user_id} cursor={cursor!r}')
            except requests.RequestException as exc:
                logger.warning('Twitch videos fetch failed for user_id=%s: %s', user_id, exc)
                complete = False
                break
            try:
                data = resp.json()
            except (ValueError, json.JSONDecodeError):
                logger.warning('Twitch videos returned invalid JSON for user_id=%s', user_id)
                complete = False
                break
            items = data.get('data', [])
            for v in items:
                thumb = v.get('thumbnail_url', '').replace('{width}', '446').replace('{height}', '251')
                raw_views = v.get('view_count', 0) or 0
                try:
                    video_views = int(raw_views)
                except (ValueError, TypeError):
                    video_views = 0
                all_videos.append(TwitchStream(
                    content_id=v['id'],
                    title=v.get('title', ''),
                    thumbnail_url=thumb,
                    started_at=v.get('created_at', ''),
                    viewer_count=video_views,
                    user_login=v.get('user_login', ''),
                    description=v.get('description', ''),
                ))
            if max_videos is not None and len(all_videos) >= max_videos:
                all_videos = all_videos[:max_videos]
                complete = False
                break
            pagination = data.get('pagination', {})
            cursor = pagination.get('cursor')
            if not cursor:
                break
        return all_videos, complete
_YT_KEY_RE = re.compile('^AIza[0-9A-Za-z_-]{35}$')
def _is_valid_yt_key(key: str) -> bool:
    """Return True if *key* looks like a real YouTube Data API v3 key."""
    return bool(_YT_KEY_RE.match(key.strip()))


def _safe_parse_platforms(raw: Any) -> list[str]:
    """Parse a platforms JSON string safely, returning [] on any failure."""
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
def load_api_keys(db: DatabaseManager) -> tuple[dict[str, str] | None, str | None]:
    """Read ``api_keys_json`` from the database.\n\nFalls back to the ``KLEOS_YT_API_KEY`` environment variable when the\nstored YouTube key is missing or fails validation.\n\nReturns ``(keys_dict, None)`` on success or ``(None, error_message)``\nwhen keys are missing or malformed so the UI can show a warning.\n"""
    raw = db.get_global_setting('api_keys_json')
    keys = {}
    if raw and raw != '{}':
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                keys = {k: v for k, v in parsed.items() if isinstance(v, str) and v.strip()}
        except json.JSONDecodeError:
            pass
    env_yt = os.environ.get('KLEOS_YT_API_KEY', '').strip()
    if env_yt and _is_valid_yt_key(env_yt):
        keys.setdefault('youtube', env_yt)
    env_cid = os.environ.get('KLEOS_TWITCH_CLIENT_ID', '').strip()
    env_cs = os.environ.get('KLEOS_TWITCH_CLIENT_SECRET', '').strip()
    if env_cid:
        keys.setdefault('twitch_client_id', env_cid)
    if env_cs:
        keys.setdefault('twitch_client_secret', env_cs)
    if not keys:
        return (None, 'No API keys configured. Open Settings to add them.')
    yt = keys.get('youtube', '')
    if yt and not _is_valid_yt_key(yt):
        logger.warning('YouTube API key fails format check (len=%d)', len(yt))
        return (None, 'YouTube API key looks invalid — it should start with \'AIza\' and be 39 characters. Open Settings to fix it.')
    return (keys, None)
def _parse_youtube_link(link: str) -> tuple[str | None, bool]:
    """Extract a handle or channel ID from a stored YouTube link.

    Returns ``(identifier, is_handle)`` where *is_handle* is True when
    the result should be passed via the ``forHandle`` parameter and False
    when it should be passed via ``id``.

    Recognised formats:
    * ``https://www.youtube.com/@handle``
    * ``@handle``
    * ``https://www.youtube.com/channel/UCxxxxx``
    * ``https://www.youtube.com/shorts/VIDEO_ID``
    * ``https://youtu.be/VIDEO_ID``
    * ``https://www.youtube.com/watch?v=VIDEO_ID``
    * Bare handle string
    """
    if not link:
        return (None, False)
    if link.startswith('@'):
        return (link.lstrip('@'), True)
    handle_match = re.search(r'youtube\.com/@([a-zA-Z0-9_.-]+)', link)
    if handle_match:
        return (handle_match.group(1), True)
    channel_match = re.search(r'youtube\.com/channel/(UC[a-zA-Z0-9_-]+)', link)
    if channel_match:
        return (channel_match.group(1), False)
    # /c/ custom URLs cannot be resolved via forHandle or id.
    # Fall back to nickname instead of failing at the API.
    custom_match = re.search(r'youtube\.com/c/([a-zA-Z0-9_.-]+)', link)
    if custom_match:
        return (None, False)
    shorts_match = re.search(r'youtube\.com/shorts/([a-zA-Z0-9_-]{11})', link)
    if shorts_match:
        return (shorts_match.group(1), False)
    short_match = re.search(r'youtu\.be/([a-zA-Z0-9_-]{11})', link)
    if short_match:
        return (short_match.group(1), False)
    watch_match = re.search(r'[?&]v=([a-zA-Z0-9_-]{11})', link)
    if watch_match:
        return (watch_match.group(1), False)
    # Bare UC channel IDs must be passed as IDs, not handles.
    if re.fullmatch(r'UC[a-zA-Z0-9_-]+', link):
        return (link, False)
    if re.fullmatch(r'[a-zA-Z0-9_.-]+', link):
        return (link, True)
    return (None, False)
def _parse_twitch_link(link: str) -> str | None:
    """Extract a Twitch login name from a stored Twitch link.

    Recognised formats:
    * ``https://www.twitch.tv/login``
    * ``https://twitch.tv/login``
    * ``https://m.twitch.tv/login``
    * Bare login name

    Returns the login string, or None if the link cannot be parsed.
    """
    if not link:
        return None
    link = link.strip()
    m = re.search(r'twitch\.tv/([a-zA-Z0-9_]+)', link)
    if m:
        return m.group(1).lower()
    if re.fullmatch(r'[a-zA-Z0-9_]+', link):
        return link.lower()
    return None
class FetchWorker(QThread):
    """Background thread that fetches media from YouTube/Twitch APIs,\ncaches thumbnails, and upserts results into the database.\n\nCommunicates **exclusively** via signals — no GUI code lives here.\n"""
    error = pyqtSignal(str)
    api_key_missing = pyqtSignal(str)
    progress = pyqtSignal(str)
    media_fetched = pyqtSignal(int)
    profile_changed = pyqtSignal()
    cooldown_active = pyqtSignal(int)
    def __init__(self, db: DatabaseManager, creator_id: int | None=None, parent: QObject | None=None) -> None:
        super().__init__(parent)
        self._db = db
        self._creator_id = creator_id
        self._cancel = threading.Event()
        self._expected_profile = ''
    def cancel(self) -> None:
        """Request the worker to stop at the next opportunity."""
        self._cancel.set()
    def run(self) -> None:
        """Entry point executed on the worker thread."""
        elapsed = time.time() - self._db.last_fetch_time
        if elapsed < _COOLDOWN_SECONDS:
            remaining = int(_COOLDOWN_SECONDS - elapsed)
            logger.info('Cooldown active — %ds remaining, skipping fetch.', remaining)
            self.cooldown_active.emit(remaining)
            return None
        keys, err = load_api_keys(self._db)
        if err:
            self.api_key_missing.emit(err)
            return None
        self._expected_profile = self._db.current_profile
        total = 0
        yt_key = keys.get('youtube')
        twitch_client_id = keys.get('twitch_client_id')
        twitch_secret = keys.get('twitch_client_secret')
        try:
            if yt_key:
                total += self._fetch_youtube(yt_key)
            if self._cancel.is_set():
                return
            if twitch_client_id and twitch_secret:
                total += self._fetch_twitch(twitch_client_id, twitch_secret)
            if not yt_key and not twitch_client_id:
                self.api_key_missing.emit('No YouTube or Twitch API keys found. Open Settings.')
                return
            self._db.last_fetch_time = time.time()
            self.media_fetched.emit(total)
            prune_cache(db=self._db)
        except Exception as exc:
            logger.exception('FetchWorker error')
            self.error.emit(str(exc))
    def _abort_if_profile_changed(self) -> bool:
        """Return True if the active profile has changed since this fetch
started, indicating the worker must abort to avoid cross-profile
data contamination.
"""
        if self._expected_profile and self._db.current_profile != self._expected_profile:
            logger.warning('Profile changed from \'%s\' to \'%s\' during fetch — aborting.', self._expected_profile, self._db.current_profile)
            self.profile_changed.emit()
            self._cancel.set()
            return True
        else:
            return False

    def _video_limit(self) -> int | None:
        """Read the per-creator video limit from settings.

        Returns None for unlimited (0 or negative), otherwise the integer limit.
        """
        raw = self._db.get_setting('fetch_video_limit') or '50'
        try:
            limit = int(raw)
        except (ValueError, TypeError):
            limit = 50
        if limit <= 0:
            return None
        return limit

    def _maybe_clear_thumbnail_cache(self, thumbnail_url: str) -> None:
        """Delete cached thumbnail so ensure_thumbnail re-downloads it.

        Called when thumbnail_quality is set to 'high' so every fetch
        gets fresh, full-resolution images.
        """
        if self._db.get_setting('thumbnail_quality') != 'high':
            return
        if not thumbnail_url:
            return
        from pathlib import Path as _Path
        local = _Path(get_thumbnail_path(thumbnail_url))
        if local.exists():
            try:
                local.unlink()
            except OSError:
                pass
    def _fetch_youtube(self, api_key: str) -> int:
        client = YouTubeClient(api_key)
        creators = self._db.get_creators()
        if self._creator_id is not None:
            creators = [c for c in creators if c['id'] == self._creator_id]
        max_videos = self._video_limit()
        count = 0
        for c in creators:
            if self._cancel.is_set():
                return count
            if self._abort_if_profile_changed():
                return count
            platforms = _safe_parse_platforms(c.get('platforms', '[]'))
            if 'youtube' not in platforms:
                continue
            self.progress.emit(f"YouTube: fetching {c['nickname']}…")
            channel_id = c.get('youtube_channel_id') or None
            is_handle = False
            if not channel_id:
                identifier, is_handle = _parse_youtube_link(c.get('youtube_link') or '')
                if not identifier:
                    identifier = c['nickname']
                    is_handle = True
                profile = client.fetch_channel_profile(identifier, is_handle=is_handle)
                if not profile or not profile.get('channel_id'):
                    if identifier != c['nickname']:
                        profile = client.fetch_channel_profile(c['nickname'], is_handle=True)
                    if not profile or not profile.get('channel_id'):
                        continue
                channel_id = profile['channel_id']
            else:
                profile = client.fetch_channel_profile(channel_id, is_handle=False)
            update_kwargs = {}
            if not c.get('youtube_channel_id') and channel_id:
                update_kwargs['youtube_channel_id'] = channel_id
            if profile and profile.get('pfp_url'):
                local_pfp = ensure_pfp(profile['pfp_url'], c['nickname'], creator_id=c['id'])
                if local_pfp:
                    update_kwargs['pfp_url'] = local_pfp
            if update_kwargs:
                self._db.update_creator(c['id'], **update_kwargs)
            if profile:
                if profile.get('subscriber_count') is not None:
                    self._db.set_setting(f"yt_channel_subscribers_{c['id']}", str(profile['subscriber_count']))
                if profile.get('view_count') is not None:
                    self._db.set_setting(f"yt_channel_views_{c['id']}", str(profile['view_count']))
            uploads_pid = profile.get('uploads_playlist_id') if profile else None
            fetch_complete = False
            try:
                videos, fetch_complete = client.fetch_latest(channel_id, uploads_playlist_id=uploads_pid, cancel_check=self._cancel.is_set, max_videos=max_videos)
            except requests.RequestException as exc:
                logger.warning('YouTube fetch failed for %s: %s', c['nickname'], exc)
                self.error.emit(f"YouTube error ({c['nickname']}): {exc}")
                videos = []
            batch = []
            yt_ids = set()
            for v in videos:
                if self._cancel.is_set():
                    break
                self._maybe_clear_thumbnail_cache(v.thumbnail_url)
                thumb_local = ensure_thumbnail(v.thumbnail_url) or ''
                batch.append({
                    'creator_id': c['id'], 'platform': 'youtube', 'content_id': v.content_id,
                    'title': v.title, 'thumbnail_path': thumb_local, 'thumbnail_url': v.thumbnail_url,
                    'upload_date': v.upload_date, 'view_count': v.view_count,
                    'is_short': v.is_short, 'description': v.description,
                })
                yt_ids.add(v.content_id)
                count += 1
            if batch:
                self._db.upsert_media_batch(batch)
            # Only prune stale videos when we fetched ALL videos successfully
            # AND were not cancelled.  With a limit, pruning would delete
            # videos that still exist on the platform but weren't fetched.
            # An incomplete fetch (fetch_complete=False) also means yt_ids
            # is a subset — pruning would delete videos we simply haven't
            # fetched yet.
            if max_videos is None and fetch_complete and yt_ids and not self._cancel.is_set():
                self._db.prune_stale_media(c['id'], 'youtube', yt_ids)
            elif not fetch_complete and yt_ids:
                logger.info('YouTube fetch for %s was incomplete (%d videos saved); skipping prune to preserve existing data', c['nickname'], len(yt_ids))
        return count

    def _fetch_twitch(self, client_id: str, client_secret: str) -> int:
        client = TwitchClient(client_id, client_secret)
        creators = self._db.get_creators()
        if self._creator_id is not None:
            creators = [c for c in creators if c['id'] == self._creator_id]
        max_videos = self._video_limit()
        count = 0
        for c in creators:
            if self._cancel.is_set():
                return count
            if self._abort_if_profile_changed():
                return count
            platforms = _safe_parse_platforms(c.get('platforms', '[]'))
            if 'twitch' not in platforms:
                continue
            self.progress.emit(f"Twitch: fetching {c['nickname']}…")
            # Resolve Twitch login from twitch_link, falling back to nickname.
            twitch_login = _parse_twitch_link(c.get('twitch_link') or '') or c['nickname'].lower()
            # Track whether each sub-fetch completed without errors so we
            # never prune based on incomplete data.
            streams_ok = False
            videos_ok = True   # Default True: considered completed when skipped
            try:
                profile = client.get_user_profile(twitch_login)
            except requests.RequestException as exc:
                logger.warning('Twitch profile fetch failed for %s: %s', c['nickname'], exc)
                self.error.emit(f"Twitch profile error ({c['nickname']}): {exc}")
                profile = None
            if profile:
                if profile.get('pfp_url'):
                    local_pfp = ensure_pfp(profile['pfp_url'], c['nickname'], creator_id=c['id'])
                    if local_pfp:
                        self._db.update_creator(c['id'], pfp_url=local_pfp)
                if profile.get('view_count') is not None:
                    self._db.set_setting(f"twitch_followers_{c['id']}", str(profile['view_count']))
            batch = []
            tw_ids = set()
            # Fetch live/recent streams
            try:
                streams = client.fetch_streams(twitch_login)
                streams_ok = True
            except requests.RequestException as exc:
                logger.warning('Twitch streams fetch failed for %s: %s', c['nickname'], exc)
                self.error.emit(f"Twitch streams error ({c['nickname']}): {exc}")
                streams = []
            for s in streams:
                if self._cancel.is_set():
                    break
                self._maybe_clear_thumbnail_cache(s.thumbnail_url)
                thumb_local = ensure_thumbnail(s.thumbnail_url) or ''
                batch.append({
                    'creator_id': c['id'], 'platform': 'twitch', 'content_id': s.content_id,
                    'title': s.title, 'thumbnail_path': thumb_local, 'thumbnail_url': s.thumbnail_url,
                    'upload_date': s.started_at, 'view_count': s.viewer_count, 'description': '',
                })
                tw_ids.add(s.content_id)
                count += 1
            # Fetch past broadcasts and highlights (respecting video limit)
            if profile and profile.get('user_id'):
                try:
                    videos, videos_ok = client.fetch_videos(profile['user_id'], cancel_check=self._cancel.is_set, max_videos=max_videos)
                except requests.RequestException as exc:
                    logger.warning('Twitch videos fetch failed for %s: %s', c['nickname'], exc)
                    self.error.emit(f"Twitch videos error ({c['nickname']}): {exc}")
                    videos = []
                    videos_ok = False
                for v in videos:
                    if self._cancel.is_set():
                        break
                    self._maybe_clear_thumbnail_cache(v.thumbnail_url)
                    thumb_local = ensure_thumbnail(v.thumbnail_url) or ''
                    batch.append({
                        'creator_id': c['id'], 'platform': 'twitch', 'content_id': v.content_id,
                        'title': v.title, 'thumbnail_path': thumb_local, 'thumbnail_url': v.thumbnail_url,
                        'upload_date': v.started_at, 'view_count': v.viewer_count, 'description': v.description,
                    })
                    tw_ids.add(v.content_id)
                    count += 1
            if batch:
                self._db.upsert_media_batch(batch)
            # If cancelled mid-creator, save what we have and return.
            if self._cancel.is_set():
                return count
            # Only prune stale videos when we fetched ALL videos AND every
            # sub-fetch (streams + videos) completed without error or
            # cancellation.  Pruning on partial data would delete content
            # that still exists on the platform.
            if (max_videos is None and tw_ids and streams_ok and videos_ok
                    and not self._cancel.is_set()):
                self._db.prune_stale_media(c['id'], 'twitch', tw_ids)
        return count