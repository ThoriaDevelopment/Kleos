"""Background worker that runs a YouTube market-research search for the
Discover window.

Quota budget (free 10K/day plan): one search ≈ 100–200 units (/search is
100/page) plus a handful of /videos + /channels units (1 per call, 50 IDs
per call).  Re-running the same query hits the DB cache and costs 0 units.

Communicates **exclusively** via signals — no GUI code lives here.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import Counter
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from .api_client import YouTubeClient, load_api_keys
from .db_manager import DatabaseManager, _utc_now
from .discover_scorer import compute_potential_score

logger = logging.getLogger(__name__)

# Hard caps to keep a single search bounded on the free quota.
_MAX_SEARCH_RESULTS = 200          # up to 4 pages of /search (400 units worst case)
_MAX_SEED_VIDEOS = 10               # recent uploads per seed channel for keyword derivation
_SEED_KEYWORD_COUNT = 6             # top-N terms derived from seed channels
_MIN_TOKEN_LEN = 4                  # ignore tokens shorter than this when deriving keywords


class DiscoverWorker(QThread):
    """Search YouTube for small, high-potential creators in a niche.

    The caller assembles a *params* dict (built by the Discover window
    from the selected search mode + filters) and starts the worker.  The
    worker:

    1. Resolves the search query (deriving keywords for seed-channel mode).
    2. Calls ``/search`` (capped pages) → video + channel IDs.
    3. Batch ``/videos`` → per-video stats (views, likes, comments, short).
    4. Batch ``/channels`` → per-channel subscriber/view/video counts.
    5. Groups videos by channel, scores each with the pure-code scorer.
    6. Filters by the sub ceiling + min views/sub, excludes already-tracked
       channels, persists results to ``search_cache`` +
       ``discovered_creators``.
    7. Emits the scored list.

    Signals
    -------
    progress(str)
        Human-readable status like "Searching…", "Scoring 24 channels…".
    results_ready(list)
        The scored + filtered discovered-creator dicts.
    error(str)
        Fatal error message.
    api_key_missing(str)
        Emitted when no YouTube API key is configured.
    aborted()
        Emitted when the user switches profile mid-search.
    """

    progress = pyqtSignal(str)
    results_ready = pyqtSignal(list)
    error = pyqtSignal(str)
    api_key_missing = pyqtSignal(str)
    aborted = pyqtSignal()

    def __init__(self, db: DatabaseManager, params: dict[str, Any], parent: Any | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._params = params
        self._cancel = threading.Event()
        self._expected_profile = ''

    def cancel(self) -> None:
        """Request the worker to stop at the next opportunity."""
        self._cancel.set()

    # ── Public helper: stable hash of the search params for cache keys ──
    @staticmethod
    def params_hash(params: dict[str, Any]) -> str:
        """Return a stable hash of the cache-relevant search params.

        Excludes transient fields so identical logical searches share a
        cache entry even if e.g. the originating UI timestamp differs.
        """
        cache_fields = (
            'query', 'region_code', 'relevance_language',
            'video_category_id', 'max_results', 'order', 'published_after',
            'sub_ceiling', 'min_subscribers', 'min_views_per_sub',
            'shorts_mode', 'seed_channels', 'result_mode',
        )
        payload = {k: params.get(k) for k in cache_fields}
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha1(raw.encode('utf-8')).hexdigest()

    def run(self) -> None:
        # Cache short-circuit: an identical prior search is returned for 0
        # quota units instead of re-hitting the /search endpoint.
        cache_key = self.params_hash(self._params)
        cached = self._db.get_cached_search(cache_key)
        if cached is not None:
            results = cached.get('results') or []
            if self._cancel.is_set():
                return
            self.results_ready.emit(results)
            return

        keys, err = load_api_keys(self._db)
        if err or not keys.get('youtube'):
            self.api_key_missing.emit(err or 'No YouTube API key found. Open Settings → API Keys.')
            return

        self._expected_profile = self._db.current_profile
        try:
            results = self._run_search(keys['youtube'])
            if self._cancel.is_set():
                return
            if self._db.current_profile != self._expected_profile:
                self.aborted.emit()
                return
            self.results_ready.emit(results)
        except Exception as exc:
            logger.exception('DiscoverWorker error')
            self.error.emit(str(exc))

    # ── Orchestration ─────────────────────────────────────────────────

    def _run_search(self, api_key: str) -> list[dict[str, Any]]:
        client = YouTubeClient(api_key)
        params = self._params

        query = (params.get('query') or '').strip()
        seed_channels = [s for s in (params.get('seed_channels') or []) if s]
        keywords: list[str] = []

        # ── Seed channels: derive a query + keywords from their uploads ──
        if seed_channels:
            self.progress.emit('Deriving keywords from seed channels…')
            seed_query, seed_keywords = self._derive_seed_keywords(client, seed_channels)
            if seed_keywords:
                # The user's explicit keywords take precedence for the
                # /search query; seed-derived keywords augment the niche_fit
                # set so scoring still rewards topical overlap with the seeds.
                if not query:
                    query = seed_query
                user_kw = [k.strip() for k in query.replace(',', ' ').split() if k.strip()]
                seen = set(user_kw)
                keywords = user_kw + [k for k in seed_keywords if k not in seen]
            elif not query:
                # Nothing to search on — emit empty result.
                return []
        elif query:
            keywords = [k.strip() for k in query.replace(',', ' ').split() if k.strip()]
        else:
            # No query and no seeds: fall back to the community's keywords
            # (verify_keywords), then the short community name, otherwise
            # rely on category/region filters alone (niche_fit will be ~0).
            query = (self._db.get_setting('verify_keywords') or '').strip()
            if not query:
                query = (self._db.get_setting('community_name') or '').strip()
            if query:
                keywords = [w for w in query.replace(',', ' ').split() if len(w) >= _MIN_TOKEN_LEN]

        max_results = min(int(params.get('max_results') or 100), _MAX_SEARCH_RESULTS)
        if self._cancel.is_set():
            return []

        # ── 1. /search (the expensive call) ──
        self.progress.emit('Searching YouTube…')
        items, _complete = client.search_videos(
            query,
            max_results=max_results,
            region_code=params.get('region_code') or None,
            relevance_language=params.get('relevance_language') or None,
            video_category_id=params.get('video_category_id') or None,
            order=params.get('order') or 'relevance',
            published_after=params.get('published_after') or None,
            cancel_check=self._cancel.is_set,
        )
        if self._cancel.is_set():
            return []
        if self._profile_changed():
            return []
        if not items:
            return []

        # ── 2. /channels batch → per-channel stats (resolve first so we can
        #    drop over-ceiling + already-tracked channels before spending
        #    /videos quota on them — /videos is cheap per call but batching
        #    only survivors keeps the free-plan budget lean). ──
        channel_ids = list({it['channel_id'] for it in items if it.get('channel_id')})
        self.progress.emit(f'Resolving {len(channel_ids)} channels…')
        channels = client.resolve_channels(channel_ids) if channel_ids else {}
        if self._cancel.is_set():
            return []
        if self._profile_changed():
            return []

        # ── 3. Filter channels by sub ceiling + min subs + tracked roster ──
        sub_ceiling = int(params.get('sub_ceiling', 0))
        min_subs = int(params.get('min_subscribers', 0))
        min_vps = float(params.get('min_views_per_sub', 0))
        shorts_mode = params.get('shorts_mode') or 'always'
        tracked_ids = self._db.tracked_channel_ids()
        survivor_cids: set[str] = set()
        for cid, ch in channels.items():
            subs = ch['subscriber_count']
            if sub_ceiling > 0 and subs > sub_ceiling:
                continue
            if min_subs > 0 and subs < min_subs:
                continue
            if cid in tracked_ids:
                continue
            survivor_cids.add(cid)

        # ── 4. /videos batch → per-video stats (only for survivors) ──
        survivor_items = [it for it in items if it.get('channel_id') in survivor_cids]
        video_ids = [it['video_id'] for it in survivor_items if it.get('video_id')]
        self.progress.emit(f'Fetching stats for {len(video_ids)} videos…')
        stats = client.fetch_video_stats(video_ids) if video_ids else {}
        if self._cancel.is_set():
            return []

        # ── 5. Group survivor videos by channel ──
        videos_by_channel: dict[str, list[dict[str, Any]]] = {}
        for it in survivor_items:
            cid = it.get('channel_id')
            if not cid or cid not in channels:
                continue
            s = stats.get(it['video_id'], {})
            videos_by_channel.setdefault(cid, []).append({
                'video_id': it['video_id'],
                'title': it.get('title', ''),
                'upload_date': it.get('published_at', ''),
                'view_count': s.get('view_count', 0),
                'like_count': s.get('like_count', 0),
                'comment_count': s.get('comment_count', 0),
                'is_short': s.get('is_short', False),
                'is_stream': s.get('is_stream', False),
                'thumbnail_url': it.get('thumbnail_url', ''),
            })

        # ── 6. Score survivors ──
        self.progress.emit(f'Scoring {len(survivor_cids)} channels…')
        results: list[dict[str, Any]] = []
        now = _utc_now()
        for cid in survivor_cids:
            if self._cancel.is_set():
                return []
            ch = channels[cid]
            subs = ch['subscriber_count']
            vids = videos_by_channel.get(cid, [])
            if not vids:
                continue
            # Shorts filter (post-hoc, by detected duration).
            if shorts_mode == 'never':
                vids = [v for v in vids if not v['is_short']]
                if not vids:
                    continue

            score = compute_potential_score(
                subscriber_count=subs,
                view_count=ch['view_count'],
                videos=vids,
                keywords=keywords,
            )
            vps = score['views_per_sub']
            if vps < min_vps:
                continue

            recent_titles = [v['title'] for v in vids[:5]]
            is_short_channel = all(v['is_short'] for v in vids) if vids else False
            results.append({
                'channel_id': cid,
                'handle': ch.get('handle', ''),
                'title': ch.get('title', ''),
                'pfp_url': ch.get('pfp_url', ''),
                'subscriber_count': subs,
                'view_count': ch['view_count'],
                'video_count': ch.get('video_count', 0),
                'cadence_per_week': score['cadence_per_week'],
                'growth_signal': score['growth_signal'],
                'engagement': score['engagement'],
                'niche_fit': score['niche_fit'],
                'views_per_sub': vps,
                'potential_score': score['score'],
                'recent_titles': recent_titles,
                'is_short_channel': is_short_channel,
                'last_refreshed_at': now,
                'sample_videos': vids,
            })

        # Sort by potential (highest first) — the agreed default.
        results.sort(key=lambda r: r['potential_score'], reverse=True)

        # ── 7. Persist ──
        # Re-check the profile immediately before writing: the scoring loop
        # above can take a while, and a switch_profile would otherwise persist
        # this search's results into the new profile's database.
        if self._profile_changed():
            return []
        self._persist(query, results)
        return results

    # ── Seed-channel keyword derivation ───────────────────────────────

    def _derive_seed_keywords(self, client: YouTubeClient, seed_channels: list[str]) -> tuple[str, list[str]]:
        """Fetch each seed channel's recent uploads and derive top keywords.

        *seed_channels* may be channel IDs or ``@handle`` strings.  For
        each, resolve then fetch a small sample of recent uploads, pool the
        title+description tokens, and return the top-N as a query string
        plus a keyword list.
        """
        if not seed_channels:
            return '', []
        pool: Counter[str] = Counter()
        for seed in seed_channels:
            if self._cancel.is_set():
                return '', []
            seed = (seed or '').strip()
            if not seed:
                continue
            is_handle = seed.startswith('@') or (not seed.startswith('UC') and len(seed) < 24)
            try:
                profile = client.fetch_channel_profile(seed, is_handle=is_handle)
            except Exception as exc:
                logger.warning('Seed channel resolve failed for %r: %s', seed, exc)
                continue
            if not profile or not profile.get('channel_id'):
                continue
            try:
                videos, _complete = client.fetch_latest(
                    profile['channel_id'],
                    uploads_playlist_id=profile.get('uploads_playlist_id'),
                    cancel_check=self._cancel.is_set,
                    max_videos=_MAX_SEED_VIDEOS,
                )
            except Exception as exc:
                logger.warning('Seed channel uploads fetch failed for %r: %s', seed, exc)
                continue
            for v in videos:
                text = (v.title or '') + ' ' + (v.description or '')
                for tok in text.lower().split():
                    tok = tok.strip('.,;:!?()[]"\'')
                    if len(tok) >= _MIN_TOKEN_LEN and tok not in _STOPWORDS:
                        pool[tok] += 1
        keywords = [w for w, _ in pool.most_common(_SEED_KEYWORD_COUNT)]
        return ' '.join(keywords), keywords

    # ── Persistence ───────────────────────────────────────────────────

    def _persist(self, query: str, results: list[dict[str, Any]]) -> None:
        """Cache the search + upsert discovered creators (without the
        heavy sample_videos field, which is only for the UI)."""
        # Cache the search itself.
        params_json = json.dumps(self._params, default=str)
        slim = []
        for r in results:
            row = {k: v for k, v in r.items() if k != 'sample_videos'}
            slim.append(row)
        self._db.save_cached_search(self.params_hash(self._params), params_json, json.dumps(slim))
        # Upsert each discovered creator.
        for r in results:
            self._db.upsert_discovered_creator(r)

    # ── Helpers ───────────────────────────────────────────────────────

    def _profile_changed(self) -> bool:
        if self._expected_profile and self._db.current_profile != self._expected_profile:
            logger.warning(
                'Profile changed from %r to %r during discover — aborting.',
                self._expected_profile, self._db.current_profile,
            )
            self.aborted.emit()
            self._cancel.set()
            return True
        return False


# Common English stopwords excluded from seed-keyword derivation so the
# derived query isn't dominated by "the"/"and"/"with" etc.
_STOPWORDS = {
    'the', 'and', 'for', 'with', 'this', 'that', 'from', 'your', 'have',
    'has', 'are', 'was', 'but', 'not', 'you', 'our', 'his', 'her', 'they',
    'their', 'its', 'all', 'any', 'can', 'will', 'just', 'like', 'what',
    'when', 'how', 'why', 'who', 'into', 'about', 'after', 'before',
}


class VideoSearchWorker(QThread):
    """Search YouTube for individual videos (the video counterpart to
    ``DiscoverWorker``'s channel search).

    Reuses the same ``/search`` (type=video) + batched ``/videos`` calls as
    the channel search, plus one batched ``/channels`` call to resolve
    subscriber counts so the same sub-ceiling / min-subs filters can apply.
    Results are cached against ``DiscoverWorker.params_hash`` with
    ``result_mode='videos'`` so a repeat search costs 0 quota units.

    Signals
    -------
    progress(str)
    results_ready(list)
        Per-video dicts (see ``_run_video_search``).
    error(str)
    api_key_missing(str)
    aborted()
    """

    progress = pyqtSignal(str)
    results_ready = pyqtSignal(list)
    error = pyqtSignal(str)
    api_key_missing = pyqtSignal(str)
    aborted = pyqtSignal()

    def __init__(self, db: DatabaseManager, params: dict[str, Any], parent: Any | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._params = dict(params)
        self._params.setdefault('result_mode', 'videos')
        self._cancel = threading.Event()
        self._expected_profile = ''

    def cancel(self) -> None:
        """Request the worker to stop at the next opportunity."""
        self._cancel.set()

    def run(self) -> None:
        cache_key = DiscoverWorker.params_hash(self._params)
        cached = self._db.get_cached_search(cache_key)
        if cached is not None:
            results = cached.get('results') or []
            if self._cancel.is_set():
                return
            self.results_ready.emit(results)
            return

        keys, err = load_api_keys(self._db)
        if err or not keys.get('youtube'):
            self.api_key_missing.emit(err or 'No YouTube API key found. Open Settings → API Keys.')
            return

        self._expected_profile = self._db.current_profile
        try:
            results = self._run_video_search(keys['youtube'])
            if self._cancel.is_set():
                return
            if self._db.current_profile != self._expected_profile:
                self.aborted.emit()
                return
            self.results_ready.emit(results)
        except Exception as exc:
            logger.exception('VideoSearchWorker error')
            self.error.emit(str(exc))

    # ── Orchestration ─────────────────────────────────────────────────

    def _run_video_search(self, api_key: str) -> list[dict[str, Any]]:
        client = YouTubeClient(api_key)
        params = self._params

        # Resolve the query: explicit query → community keywords → community name.
        query = (params.get('query') or '').strip()
        if not query:
            query = (self._db.get_setting('verify_keywords') or '').strip()
        if not query:
            query = (self._db.get_setting('community_name') or '').strip()

        max_results = min(int(params.get('max_results') or 100), _MAX_SEARCH_RESULTS)
        if self._cancel.is_set():
            return []

        # ── 1. /search (the expensive call) ──
        self.progress.emit('Searching YouTube…')
        items, _complete = client.search_videos(
            query,
            max_results=max_results,
            region_code=params.get('region_code') or None,
            relevance_language=params.get('relevance_language') or None,
            video_category_id=params.get('video_category_id') or None,
            order=params.get('order') or 'relevance',
            published_after=params.get('published_after') or None,
            cancel_check=self._cancel.is_set,
        )
        if self._cancel.is_set() or self._profile_changed() or not items:
            return []

        # ── 2. /channels batch → subscriber counts (for sub-ceiling filtering) ──
        channel_ids = list({it['channel_id'] for it in items if it.get('channel_id')})
        self.progress.emit(f'Resolving {len(channel_ids)} channels…')
        channels = client.resolve_channels(channel_ids) if channel_ids else {}
        if self._cancel.is_set() or self._profile_changed():
            return []

        # ── 3. Filter channels by sub ceiling + min subs + tracked roster ──
        sub_ceiling = int(params.get('sub_ceiling', 0))
        min_subs = int(params.get('min_subscribers', 0))
        shorts_mode = params.get('shorts_mode') or 'always'
        tracked_ids = self._db.tracked_channel_ids()
        survivor_cids: set[str] = set()
        for cid, ch in channels.items():
            subs = ch['subscriber_count']
            if sub_ceiling > 0 and subs > sub_ceiling:
                continue
            if min_subs > 0 and subs < min_subs:
                continue
            if cid in tracked_ids:
                continue
            survivor_cids.add(cid)

        survivor_items = [it for it in items if it.get('channel_id') in survivor_cids]
        if not survivor_items:
            return []

        # ── 4. /videos batch → per-video stats (view/like/comment, short/stream) ──
        video_ids = [it['video_id'] for it in survivor_items if it.get('video_id')]
        self.progress.emit(f'Fetching stats for {len(video_ids)} videos…')
        stats = client.fetch_video_stats(video_ids) if video_ids else {}
        if self._cancel.is_set():
            return []

        # ── 5. Build per-video results ──
        results: list[dict[str, Any]] = []
        for it in survivor_items:
            cid = it.get('channel_id')
            if not cid or cid not in channels:
                continue
            s = stats.get(it['video_id'], {})
            is_short = bool(s.get('is_short', False))
            is_stream = bool(s.get('is_stream', False))
            if shorts_mode == 'never' and is_short:
                continue
            ch = channels[cid]
            results.append({
                'video_id': it['video_id'],
                'title': it.get('title', ''),
                'channel_id': cid,
                'channel_title': it.get('channel_title', '') or ch.get('title', ''),
                'handle': ch.get('handle', ''),
                'pfp_url': ch.get('pfp_url', ''),
                'subscriber_count': ch['subscriber_count'],
                'view_count': int(s.get('view_count', 0) or 0),
                'like_count': int(s.get('like_count', 0) or 0),
                'comment_count': int(s.get('comment_count', 0) or 0),
                'upload_date': it.get('published_at', ''),
                'is_short': is_short,
                'is_stream': is_stream,
                'thumbnail_url': it.get('thumbnail_url', ''),
            })

        # ── 6. Cache (no discovered_creators persistence — video results are
        #    session-scoped; re-running reads from the cache for 0 units). ──
        # Re-check the profile before writing the cache so a switch_profile
        # can't store these results under the new profile's cache key.
        if self._profile_changed():
            return []
        params_json = json.dumps(self._params, default=str)
        self._db.save_cached_search(
            DiscoverWorker.params_hash(self._params), params_json, json.dumps(results),
        )
        return results

    # ── Helpers ───────────────────────────────────────────────────────

    def _profile_changed(self) -> bool:
        if self._expected_profile and self._db.current_profile != self._expected_profile:
            logger.warning(
                'Profile changed from %r to %r during video search — aborting.',
                self._expected_profile, self._db.current_profile,
            )
            self.aborted.emit()
            self._cancel.set()
            return True
        return False