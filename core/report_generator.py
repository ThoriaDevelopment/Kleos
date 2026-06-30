"""Generate plain-text analytics reports from the Kleos database.

Reports are designed for clipboard sharing — human-readable, plain-text
summaries suitable for pasting into Discord, forums, or community channels.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from core.db_manager import DatabaseManager
from ui.components.creator_card import _compact_number


def _build_filter_clause(verified_only: bool, content_type: str | None) -> str:
    """Return a SQL AND-clause fragment combining verified and content-type filters.

    Args:
        verified_only: If True, add ``AND is_verified = 1``.
        content_type: ``None`` (all types), ``'short'``, ``'video'``, ``'stream'``.
    """
    conditions: list[str] = []
    if verified_only:
        conditions.append('is_verified = 1')
    if content_type == 'short':
        conditions.append('is_short = 1')
    elif content_type == 'video':
        conditions.append('is_short = 0')
        conditions.append('is_stream = 0')
    elif content_type == 'stream':
        conditions.append('is_stream = 1')
    if not conditions:
        return ''
    return 'AND ' + ' AND '.join(conditions)


def _filter_label(verified_only: bool, content_type: str | None) -> str:
    """Return a human-readable label for the current filter combination."""
    type_labels: dict[str | None, str] = {
        None:      'Content',
        'short':   'Shorts',
        'video':   'Videos',
        'stream':  'Streams',
    }
    type_part = type_labels.get(content_type, 'Content')
    prefix = 'Verified' if verified_only else 'All'
    return f'{prefix} {type_part}'


def generate_report(db: DatabaseManager, period: str = 'monthly', role_id: int | None = None, verified_only: bool = True, content_type: str | None = None, creator_id: int | None = None) -> str:
    """Generate a human-readable plain-text analytics report.

    Args:
        db: DatabaseManager instance for the active profile.
        period: 'weekly', 'monthly', or 'yearly' — controls the date range.
        role_id: Optional role filter — only include creators with this role.
        verified_only: When True (default), only count verified content.
        content_type: Optional content-type filter.
            Accepted values: None (all types), 'short', 'video', 'stream'.
        creator_id: Optional creator filter — only include this creator.

    Returns:
        A multi-line plain-text string suitable for clipboard sharing.
    """
    now = datetime.now(timezone.utc)
    if period == 'weekly':
        since = now - timedelta(weeks=1)
        period_label = 'Weekly'
    elif period == 'yearly':
        since = now - timedelta(days=365)
        period_label = 'Yearly'
    elif period == 'all':
        since = None
        period_label = 'All Time'
    else:  # monthly
        since = now - timedelta(days=30)
        period_label = 'Monthly'

    since_str = since.strftime('%Y-%m-%dT%H:%M:%SZ') if since else ''

    # Filter creators by role if requested
    creators = db.get_creators()
    if role_id is not None:
        creators = [c for c in creators if c.get('role_id') == role_id]
    if creator_id is not None:
        creators = [c for c in creators if c['id'] == creator_id]

    roles = {r['id']: r for r in db.get_roles()}
    sub_counts = db.bulk_subscriber_counts()

    content_clause = _build_filter_clause(verified_only, content_type)
    content_label = _filter_label(verified_only, content_type)

    lines: list[str] = []
    lines.append('=== Kleos Analytics Report ===')
    if since:
        lines.append(f'Period: {since.strftime("%b %d, %Y")} - {now.strftime("%b %d, %Y")}')
    else:
        lines.append(f'Period: All Time')
    lines.append(f'Filter: {content_label}')

    # Per-creator stats within the period (one grouped query instead of N+1)
    date_clause = f"AND upload_date >= '{since_str}'" if since_str else ''
    media_stats = db.bulk_media_stats(content_clause, date_clause)
    total_views = 0
    total_uploads = 0
    creator_stats: list[dict[str, Any]] = []

    for c in creators:
        cid = c['id']
        views, count = media_stats.get(cid, (0, 0))
        total_views += views
        total_uploads += count

        counts = sub_counts.get(cid, {})
        sub_parts = []
        if counts.get('youtube', 0):
            sub_parts.append(f'{_compact_number(counts["youtube"])} subs')
        if counts.get('twitch', 0):
            sub_parts.append(f'{_compact_number(counts["twitch"])} flw')

        creator_stats.append({
            'nickname': c['nickname'],
            'views': views,
            'uploads': count,
            'sub_text': ' | '.join(sub_parts) if sub_parts else 'N/A',
        })

    lines.append(f'Total Uploads ({content_label}): {total_uploads:,}')
    lines.append(f'Total Views (period): {total_views:,}')
    lines.append('')

    # Leaderboard sorted by views
    lines.append('--- Leaderboard ---')
    creator_stats.sort(key=lambda s: s['views'], reverse=True)
    for i, cs in enumerate(creator_stats, 1):
        lines.append(
            f'{i}. {cs["nickname"]} — {cs["views"]:,} views, '
            f'{cs["uploads"]} uploads | {cs["sub_text"]}'
        )

    lines.append('')
    lines.append(f'Generated by Kleos on {now.strftime("%Y-%m-%d %H:%M UTC")}')
    return '\n'.join(lines)