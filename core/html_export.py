"""Generate a self-contained HTML community dashboard from the Kleos database.

The output is a single ``<html>`` document with all CSS inlined and charts
embedded as inline SVG — no external dependencies — so it can be shared,
archived, or published as-is.
"""
from __future__ import annotations

import html
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from io import BytesIO
from typing import Any

from matplotlib.figure import Figure

from core.db_manager import DatabaseManager
from core.report_generator import generate_report, _build_filter_clause, _filter_label
from ui.components.creator_card import _compact_number
from ui.theme.tokens import C


# ---------------------------------------------------------------------------
# Colour mapping from design tokens (used both in CSS constants below and
# in dynamic HTML generation).
# ---------------------------------------------------------------------------
_PALETTE: dict[str, str] = {
    'bg_deep':    C.BG_DEEP,
    'bg_base':    C.BG_BASE,
    'bg_layer':   C.BG_LAYER,
    'bg_raised':  C.BG_RAISED,
    'bg_float':  C.BG_FLOAT,
    'bg_hover':   C.BG_HOVER,
    'text_primary':   C.TEXT_PRIMARY,
    'text_secondary': C.TEXT_SECONDARY,
    'text_muted':     C.TEXT_MUTED,
    'accent':          C.ACCENT,
    'accent_hover':    C.ACCENT_HOVER,
    'accent_press':    C.ACCENT_PRESS,
    'border':          C.BORDER,
    'danger':          C.DANGER,
    'success':         C.SUCCESS,
}

# Multi-creator line chart colours (cycled)
_CHART_COLORS = [
    C.ACCENT, '#9B59B6', '#2ECC71', '#E74C3C', '#F39C12',
    '#1ABC9C', '#E67E22', '#3498DB',
]

# ---------------------------------------------------------------------------
# Inline CSS (embedded in every generated page)
# ---------------------------------------------------------------------------
_CSS = """\
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html{{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
    background:{bg_deep};color:{text_primary};line-height:1.55}}
body{{max-width:960px;margin:0 auto;padding:24px 16px}}
a{{color:{accent};text-decoration:none}}
a:hover{{text-decoration:underline}}

/* ---- header ---- */
.header{{text-align:center;margin-bottom:32px;padding-bottom:16px;
         border-bottom:1px solid {border}}}
.header h1{{font-size:1.6rem;font-weight:700;color:{text_primary};
            margin-bottom:4px}}
.header .subtitle{{font-size:.9rem;color:{text_secondary}}}
.header .period{{font-size:.85rem;color:{accent};margin-top:6px}}

/* ---- cards grid ---- */
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
        gap:16px;margin-bottom:32px}}
.card{{background:{bg_raised};border:1px solid {border};border-radius:10px;
       padding:18px;transition:box-shadow .2s ease,border-color .2s ease}}
.card:hover{{border-color:{accent};box-shadow:0 0 12px rgba(74,144,217,.15)}}
.card .nickname{{font-size:1.05rem;font-weight:600;color:{text_primary};
                margin-bottom:6px;display:flex;align-items:center;gap:8px}}
.card .platform-tag{{font-size:.75rem;color:{text_muted};background:{bg_float};
                     border-radius:4px;padding:2px 7px}}
.card .role-badge{{font-size:.7rem;font-weight:600;border-radius:4px;
                   padding:2px 8px;display:inline-block;margin-bottom:8px}}
.card .stats{{display:flex;gap:20px;margin-top:6px}}
.card .stat{{display:flex;flex-direction:column}}
.card .stat-label{{font-size:.7rem;color:{text_muted};text-transform:uppercase;
                    letter-spacing:.04em}}
.card .stat-value{{font-size:1rem;font-weight:600;color:{text_primary}}}

/* ---- charts ---- */
.chart{{background:{bg_raised};border:1px solid {border};border-radius:10px;
         padding:18px;margin-bottom:32px}}
.chart h2{{font-size:1rem;font-weight:600;margin-bottom:12px;color:{text_primary}}}
.chart svg{{width:100%;height:auto}}

/* ---- summary table ---- */
.summary{{background:{bg_raised};border:1px solid {border};border-radius:10px;
          padding:18px;margin-bottom:32px}}
.summary h2{{font-size:1rem;font-weight:600;margin-bottom:12px;color:{text_primary}}}
.summary table{{width:100%;border-collapse:collapse}}
.summary th,.summary td{{text-align:left;padding:8px 12px;
                          border-bottom:1px solid {border}}}
.summary th{{font-size:.75rem;color:{text_muted};text-transform:uppercase;
             letter-spacing:.04em}}
.summary td{{font-size:.9rem;color:{text_primary}}}
.summary tr:last-child th,.summary tr:last-child td{{border-bottom:none}}

/* ---- footer ---- */
.footer{{text-align:center;font-size:.75rem;color:{text_muted};
         padding-top:16px;border-top:1px solid {border}}}

/* ---- responsive ---- */
@media(max-width:600px){{
  .cards{{grid-template-columns:1fr}}
  .header h1{{font-size:1.3rem}}
}}
""".format(**_PALETTE)


# ---------------------------------------------------------------------------
# Helper: text-contrast colour for role badges
# ---------------------------------------------------------------------------
def _badge_text(bg_hex: str) -> str:
    """Return white or dark text depending on the luminance of *bg_hex*."""
    try:
        r, g, b = int(bg_hex[1:3], 16), int(bg_hex[3:5], 16), int(bg_hex[5:7], 16)
    except (ValueError, IndexError):
        return '#FFFFFF'
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return '#111111' if luminance > 150 else '#FFFFFF'


# ---------------------------------------------------------------------------
# Chart SVG generation helpers
# ---------------------------------------------------------------------------
def _apply_chart_style(fig: Figure) -> None:
    """Apply theme-consistent colours to a matplotlib Figure for SVG export."""
    fig.patch.set_facecolor(_PALETTE['bg_raised'])
    fig.patch.set_edgecolor(_PALETTE['bg_raised'])
    fig.patch.set_linewidth(0)
    for ax in fig.axes:
        ax.set_facecolor(_PALETTE['bg_layer'])
        ax.tick_params(colors=_PALETTE['text_secondary'])
        ax.xaxis.label.set_color(_PALETTE['text_primary'])
        ax.yaxis.label.set_color(_PALETTE['text_primary'])
        ax.title.set_color(_PALETTE['text_primary'])
        for spine in ax.spines.values():
            spine.set_color(_PALETTE['border'])
        ax.grid(True, color=_PALETTE['border'], alpha=0.5)


def _fig_to_svg(fig: Figure) -> str:
    """Render a matplotlib Figure to an SVG string."""
    buf = BytesIO()
    fig.savefig(buf, format='svg', bbox_inches='tight')
    buf.seek(0)
    svg = buf.read().decode('utf-8')
    buf.close()
    return svg


def _generate_timeline_svg(
    db: DatabaseManager,
    content_clause: str,
    date_clause: str,
    platform_clause: str,
    chart_title: str,
    creator_id: int | None = None,
) -> str:
    """Generate an SVG timeline chart of view counts over time per creator.

    Returns an SVG string, or an empty string if there is no data.
    """
    conditions = ["m.upload_date != ''", "m.creator_id = c.id"]
    params: list[Any] = []
    if content_clause:
        conditions.append(content_clause.replace('AND ', '', 1))
    if date_clause:
        conditions.append(date_clause.replace('AND ', '', 1))
    if platform_clause:
        conditions.append(platform_clause.replace('AND ', '', 1))
    if creator_id is not None:
        conditions.append('m.creator_id = ?')
        params.append(creator_id)
    where = ' AND '.join(conditions)
    rows = db._read(
        f'SELECT m.upload_date, m.view_count, c.nickname '
        f'FROM media_content m, creators c '
        f'WHERE {where} ORDER BY m.upload_date ASC',
        tuple(params),
    )
    if not rows:
        return ''

    by_creator: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for r in rows:
        by_creator[r['nickname']].append((r['upload_date'], r['view_count']))

    fig = Figure(figsize=(8, 4), dpi=100)
    ax = fig.add_subplot(111)
    for i, (nick, points) in enumerate(by_creator.items()):
        dates = []
        views = []
        for ds, vc in sorted(points, key=lambda p: p[0]):
            try:
                dt = datetime.fromisoformat(ds.replace('Z', '+00:00'))
                dates.append(dt)
                views.append(vc)
            except (ValueError, TypeError):
                pass
        if dates:
            ax.plot(dates, views, marker='o', markersize=3, label=nick,
                    color=_CHART_COLORS[i % len(_CHART_COLORS)], linewidth=1.5)
    if not ax.lines:
        fig.clear()
        return ''

    ax.set_xlabel('Date')
    ax.set_ylabel('Views')
    ax.set_title(chart_title)
    ax.legend(fontsize=8, facecolor=_PALETTE['bg_float'], edgecolor=_PALETTE['border'],
              labelcolor=_PALETTE['text_primary'])
    _apply_chart_style(fig)
    fig.autofmt_xdate()
    return _fig_to_svg(fig)


def _generate_bar_svg(
    db: DatabaseManager,
    content_clause: str,
    date_clause: str,
    platform_clause: str,
    chart_title: str,
    creator_id: int | None = None,
) -> str:
    """Generate an SVG bar chart of monthly upload counts.

    Returns an SVG string, or an empty string if there is no data.
    """
    conditions = ["upload_date != ''"]
    params: list[Any] = []
    if content_clause:
        conditions.append(content_clause.replace('AND ', '', 1))
    if date_clause:
        conditions.append(date_clause.replace('AND ', '', 1))
    if platform_clause:
        conditions.append(platform_clause.replace('AND ', '', 1))
    if creator_id is not None:
        conditions.append('creator_id = ?')
        params.append(creator_id)
    where = ' AND '.join(conditions)
    rows = db._read(
        f'SELECT upload_date FROM media_content WHERE {where} ORDER BY upload_date ASC',
        tuple(params),
    )
    if not rows:
        return ''

    month_counts: dict[str, int] = defaultdict(int)
    for r in rows:
        try:
            dt = datetime.fromisoformat(r['upload_date'].replace('Z', '+00:00'))
            key = dt.strftime('%Y-%m')
            month_counts[key] += 1
        except (ValueError, TypeError):
            pass
    months = sorted(month_counts.keys())
    counts = [month_counts[m] for m in months]
    labels = []
    for m in months:
        try:
            dt = datetime.strptime(m, '%Y-%m')
            labels.append(dt.strftime('%b %y'))
        except ValueError:
            labels.append(m)

    fig = Figure(figsize=(8, 4), dpi=100)
    ax = fig.add_subplot(111)
    bar_colors = [_PALETTE['accent']] * len(months)
    ax.bar(range(len(months)), counts, color=bar_colors, width=0.6,
           edgecolor=_PALETTE['border'], linewidth=0.5)
    ax.set_xticks(range(len(months)))
    ax.set_xticklabels(labels, rotation=45, fontsize=8)
    ax.set_ylabel('Uploads')
    ax.set_title(chart_title)
    _apply_chart_style(fig)
    fig.tight_layout()
    return _fig_to_svg(fig)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate_html_report(
    db: DatabaseManager,
    period: str = 'monthly',
    role_id: int | None = None,
    verified_only: bool = True,
    content_type: str | None = None,
    platform: str | None = None,
    time_range: str | None = None,
    creator_id: int | None = None,
) -> str:
    """Generate a self-contained HTML community dashboard page.

    Args:
        db: DatabaseManager instance for the active profile.
        period: ``'weekly'``, ``'monthly'``, ``'yearly'``, or ``'all'`` — controls the
            date range for statistics.
        role_id: Optional role filter — only include creators with this role.
        verified_only: When *True* (default), only count verified content.
        content_type: Optional content-type filter.
            Accepted values: None (all types), 'short', 'video', 'stream'.
        platform: Optional platform filter — 'youtube' or 'twitch'.
        time_range: Optional time range for charts — 'week', 'month', 'year', or None.
        creator_id: Optional creator filter — only include this creator.

    Returns:
        A complete HTML document string.
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

    # Build SQL filter clauses and human-readable label
    content_clause = _build_filter_clause(verified_only, content_type)
    content_label = _filter_label(verified_only, content_type)
    date_clause = f"AND upload_date >= '{since_str}'" if since_str else ''
    # Time-range filter for charts (may differ from report period)
    if time_range == 'week':
        chart_since = now - timedelta(weeks=1)
    elif time_range == 'month':
        chart_since = now - timedelta(days=30)
    elif time_range == 'year':
        chart_since = now - timedelta(days=365)
    elif time_range is None:
        # Fall back to report period so charts match the selected timeframe
        if period == 'weekly':
            chart_since = now - timedelta(weeks=1)
        elif period == 'monthly':
            chart_since = now - timedelta(days=30)
        elif period == 'yearly':
            chart_since = now - timedelta(days=365)
        else:
            chart_since = None
    else:
        chart_since = None
    chart_date_clause = f"AND upload_date >= '{chart_since.strftime('%Y-%m-%dT%H:%M:%SZ')}'" if chart_since else ''
    platform_clause = f"AND platform = '{platform}'" if platform else ''

    # ---- Gather data ----
    community_name = db.get_setting('community_description') or 'Kleos Community'
    creators = db.get_creators()
    if role_id is not None:
        creators = [c for c in creators if c.get('role_id') == role_id]
    if creator_id is not None:
        creators = [c for c in creators if c['id'] == creator_id]

    roles: dict[int, dict[str, Any]] = {r['id']: r for r in db.get_roles()}
    sub_counts: dict[int, dict[str, int]] = db.bulk_subscriber_counts()

    total_views = 0
    total_uploads = 0
    creator_cards: list[str] = []

    for c in creators:
        cid = c['id']
        rows = db._read(
            f"SELECT COALESCE(SUM(view_count), 0) AS views, COUNT(*) AS count "
            f"FROM media_content WHERE creator_id = ? {content_clause} {date_clause}",
            (cid,),
        )
        views = rows[0]['views'] if rows else 0
        count = rows[0]['count'] if rows else 0
        total_views += views
        total_uploads += count

        # Role badge
        role = roles.get(c.get('role_id'))
        if role:
            role_color = role.get('role_color', C.ACCENT)
            role_name = role.get('role_name', 'Unknown')
            badge_fg = _badge_text(role_color)
            badge_html = (
                f'<span class="role-badge" style="background:{html.escape(role_color)};'
                f'color:{html.escape(badge_fg)}">{html.escape(role_name)}</span>'
            )
        else:
            badge_html = ''

        # Platform tags
        import json as _json
        platforms = _json.loads(c.get('platforms', '[]')) if isinstance(c.get('platforms'), str) else (c.get('platforms') or [])
        platform_tags = ' '.join(
            f'<span class="platform-tag">{html.escape(p)}</span>' for p in platforms
        )

        # Subscriber counts
        counts = sub_counts.get(cid, {})
        yt_subs = counts.get('youtube', 0)
        tw_followers = counts.get('twitch', 0)

        creator_cards.append(
            f'<div class="card">\n'
            f'  <div class="nickname">{html.escape(c["nickname"])} {platform_tags}</div>\n'
            f'  {badge_html}\n'
            f'  <div class="stats">\n'
            f'    <div class="stat">\n'
            f'      <span class="stat-label">Subscribers</span>\n'
            f'      <span class="stat-value">{_compact_number(yt_subs + tw_followers)}</span>\n'
            f'    </div>\n'
            f'    <div class="stat">\n'
            f'      <span class="stat-label">Views ({period_label})</span>\n'
            f'      <span class="stat-value">{_compact_number(views)}</span>\n'
            f'    </div>\n'
            f'    <div class="stat">\n'
            f'      <span class="stat-label">Uploads ({period_label})</span>\n'
            f'      <span class="stat-value">{count:,}</span>\n'
            f'    </div>\n'
            f'  </div>\n'
            f'</div>'
        )

    # ---- Generate charts ----
    timeline_title = f'{content_label} — View Trajectory'
    bar_title = f'Monthly {content_label} Upload Activity'
    timeline_svg = _generate_timeline_svg(db, content_clause, chart_date_clause, platform_clause, timeline_title, creator_id=creator_id)
    bar_svg = _generate_bar_svg(db, content_clause, chart_date_clause, platform_clause, bar_title, creator_id=creator_id)

    # ---- Assemble HTML ----
    cards_html = '\n'.join(creator_cards)
    timestamp = now.strftime('%Y-%m-%d %H:%M UTC')

    timeline_section = ''
    if timeline_svg:
        timeline_section = (
            f'<section class="chart">\n'
            f'  <h2>{html.escape(timeline_title)}</h2>\n'
            f'  {timeline_svg}\n'
            f'</section>\n'
        )
    bar_section = ''
    if bar_svg:
        bar_section = (
            f'<section class="chart">\n'
            f'  <h2>{html.escape(bar_title)}</h2>\n'
            f'  {bar_svg}\n'
            f'</section>\n'
        )

    # Build summary labels that reflect the selected timeframe
    if period == 'all':
        uploads_label = content_label
        views_label = 'Total views'
    else:
        uploads_label = f'{period_label} {content_label}'
        views_label = f'{period_label} total views'

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{html.escape(community_name)} — Kleos Community Dashboard</title>
<style>{_CSS}</style>
</head>
<body>

<div class="header">
  <h1>{html.escape(community_name)}</h1>
  <div class="subtitle">Kleos Community Dashboard</div>
  <div class="period">{period_label} &middot; {since.strftime('%b %d, %Y') + ' – ' + now.strftime('%b %d, %Y') if since else 'All data'}</div>
</div>

<section class="cards">
{cards_html}
</section>

{timeline_section}{bar_section}
<section class="summary">
  <h2>Totals</h2>
  <table>
    <tr><th>{uploads_label}</th><td>{total_uploads:,}</td></tr>
    <tr><th>{views_label}</th><td>{total_views:,}</td></tr>
  </table>
</section>

<footer class="footer">
  Generated by <a href="https://github.com/ThoriaDevelopment/Kleos">Kleos</a> on {timestamp}
</footer>

</body>
</html>"""

    return page