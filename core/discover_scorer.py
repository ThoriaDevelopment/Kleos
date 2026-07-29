"""Pure-code potential scorer for discovered YouTube channels.

No AI, no network.  Given a channel's stats and a sample of its recent
uploads, ``compute_potential_score`` returns a 0–100 potential score plus
the per-signal sub-scores so the UI can show a breakdown.

Signal weights (agreed):
    views_per_sub      35  — underviewed audience (the core signal)
    upload consistency 20  — uploads/week over the recent window
    growth signal      20  — recent-video view velocity vs channel size
    niche fit          15  — keyword overlap of titles vs search terms
    engagement         10  — (likes + comments) / views on recent videos
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from functools import lru_cache


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None


def _views_per_sub(subscriber_count: int, view_count: int) -> float:
    """Total channel views divided by subscribers (0 if no subs)."""
    if subscriber_count <= 0:
        return 0.0
    return view_count / subscriber_count


def _cadence_per_week(videos: list[dict], window_days: int = 90) -> float:
    """Average uploads per week over the last *window_days* days.

    Each video dict must have an ``upload_date`` ISO string.  Videos
    outside the window are ignored.  Returns 0.0 if no timestamps parse
    or no videos fall in the window.
    """
    if not videos:
        return 0.0
    cutoff = datetime.now(timezone.utc).timestamp() - window_days * 86400
    in_window = 0
    for v in videos:
        dt = _parse_iso(v.get('upload_date', ''))
        if dt is None:
            continue
        if dt.timestamp() >= cutoff:
            in_window += 1
    return in_window / (window_days / 7.0)


def _growth_signal(videos: list[dict], subscriber_count: int) -> float:
    """Recent-video view velocity relative to channel size.

    For each of the most recent videos (newest first), compute
    ``views / max(subs, 1)``.  A channel whose recent videos pull many
    multiples of its subscriber count is "heating up".  We average the
    top-3 recent ratios and cap so one viral Short can't dominate.

    This is the agreed proxy for growth velocity (true sub-growth would
    require periodic snapshots, which the user declined for non-roster
    creators).
    """
    if not videos or subscriber_count <= 0:
        return 0.0
    subs = max(subscriber_count, 1)
    # Sort newest first by upload_date.
    parsed = []
    for v in videos:
        dt = _parse_iso(v.get('upload_date', ''))
        if dt is not None:
            parsed.append((dt, int(v.get('view_count', 0) or 0)))
    if not parsed:
        return 0.0
    parsed.sort(key=lambda p: p[0], reverse=True)
    ratios = [views / subs for _, views in parsed[:3]]
    if not ratios:
        return 0.0
    avg = sum(ratios) / len(ratios)
    # Cap at 10x subs so a single breakout doesn't saturate the score.
    return min(avg, 10.0)


def _engagement(videos: list[dict]) -> float:
    """Average (likes + comments) / views across recent videos.

    Each video dict may carry ``like_count`` and ``comment_count``.  If
    those are absent the engagement signal quietly degrades to 0 — the
    score just leans on the other signals.
    """
    ratios = []
    for v in videos:
        views = int(v.get('view_count', 0) or 0)
        if views <= 0:
            continue
        likes = int(v.get('like_count', 0) or 0)
        comments = int(v.get('comment_count', 0) or 0)
        ratios.append((likes + comments) / views)
    if not ratios:
        return 0.0
    return sum(ratios) / len(ratios)


def _tokenize(text: str) -> set[str]:
    """Lowercase alphanumeric token set, dropping 2-char noise."""
    return {t for t in re.findall(r'[a-z0-9]+', (text or '').lower()) if len(t) > 2}


@lru_cache(maxsize=256)
def _keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern:
    """Build + memoize a single combined regex for a keyword set.

    Compiling N separate per-keyword patterns per channel per call is
    wasteful when the same keyword set scores many channels in one
    search.  A single alternation (``\\b(kw1|kw2|…)\\b``) does the same
    job in one ``search`` per title, and is cached on the keyword tuple
    so repeated searches with the same keywords skip recompilation.
    """
    return re.compile(
        r'\b(' + '|'.join(re.escape(k) for k in keywords) + r')\b',
        re.IGNORECASE,
    )


def _niche_fit(videos: list[dict], keywords: list[str]) -> float:
    """Overlap of recent video titles with the search keywords.

    Returns the fraction (0..1) of recent videos whose title contains at
    least one keyword (case-insensitive whole-word-ish match).  When no
    keywords are supplied (e.g. category-only search) returns 0 — the
    signal simply doesn't contribute, which is fine.
    """
    if not videos or not keywords:
        return 0.0
    kws = tuple(k.strip().lower() for k in keywords if k and k.strip())
    if not kws:
        return 0.0
    pattern = _keyword_pattern(kws)
    hits = 0
    total = 0
    for v in videos:
        title = v.get('title', '') or ''
        if not title:
            continue
        total += 1
        if pattern.search(title):
            hits += 1
    if total == 0:
        return 0.0
    return hits / total


def _normalize(value: float, cap: float) -> float:
    """Linear normalise to 0..1, clamping at *cap*."""
    if cap <= 0:
        return 0.0
    return min(max(value, 0.0), cap) / cap


def compute_potential_score(
    *,
    subscriber_count: int,
    view_count: int,
    videos: list[dict],
    keywords: list[str] | None = None,
) -> dict:
    """Return ``{score, views_per_sub, cadence, growth, engagement, niche_fit}``.

    *score* is an int 0–100; the rest are the raw sub-signal values for
    display.  *videos* is a list of dicts each with at least
    ``upload_date``, ``view_count``, ``title``, and optionally
    ``like_count`` / ``comment_count``.
    """
    keywords = keywords or []
    vps = _views_per_sub(subscriber_count, view_count)
    cadence = _cadence_per_week(videos)
    growth = _growth_signal(videos, subscriber_count)
    engagement = _engagement(videos)
    niche = _niche_fit(videos, keywords)

    # Normalise each signal to 0..1 against a sensible cap.
    n_vps = _normalize(vps, 100.0)          # 100 views/sub ≈ saturation
    n_cadence = _normalize(cadence, 5.0)     # 5 uploads/week ≈ saturation
    n_growth = _normalize(growth, 5.0)       # 5x subs avg on recent ≈ saturation
    n_engagement = _normalize(engagement, 0.10)  # 10% engagement ≈ saturation
    n_niche = niche                          # already 0..1

    score = round(
        n_vps * 35
        + n_cadence * 20
        + n_growth * 20
        + n_niche * 15
        + n_engagement * 10
    )
    # Clamp to a clean 0..100 range.
    score = max(0, min(100, score))
    return {
        'score': score,
        'views_per_sub': vps,
        'cadence_per_week': cadence,
        'growth_signal': growth,
        'engagement': engagement,
        'niche_fit': niche,
    }