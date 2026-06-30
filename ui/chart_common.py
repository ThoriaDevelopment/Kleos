"""Shared chart helpers: matplotlib styling, the standard SQL filter
condition builder, the per-theme series palette, and the no-dependency
monotone Catmull-Rom→Bézier smoothing used by the timeline charts.

Kept separate from :mod:`ui.chart_utils` (the zoom/pan canvas mixin) so the
two concerns don't tangle.  Everything here re-reads the live theme tokens at
call time, so a theme switch recolours charts on the next ``_render()``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from matplotlib.figure import Figure
from matplotlib.patches import PathPatch
from matplotlib.path import Path

from ui.theme.tokens import C

# ---------------------------------------------------------------------------
# Matplotlib styling
# ---------------------------------------------------------------------------
def mpl_style() -> dict:
    """Return a matplotlib style dict built from the *current* theme tokens."""
    return {
        'figure.facecolor': C.DIALOG_BG, 'axes.facecolor': C.INPUT_BG,
        'axes.edgecolor': C.BORDER, 'axes.labelcolor': C.TEXT_PRIMARY,
        'xtick.color': C.TEXT_SECONDARY, 'ytick.color': C.TEXT_SECONDARY,
        'text.color': C.TEXT_PRIMARY, 'grid.color': C.BORDER,
        'grid.alpha': 0.5, 'lines.color': C.ACCENT,
    }


def apply_style(fig: Figure, *, facecolor: str | None = None,
                edgecolor: str | None = None) -> None:
    """Apply theme-consistent colours to every axes of ``fig``.

    ``facecolor`` / ``edgecolor`` default to the dialog figure background; the
    HTML exporter passes the raised-card background so exported charts match
    the surrounding page.
    """
    s = mpl_style()
    fig_bg = facecolor or s['figure.facecolor']
    fig.patch.set_facecolor(fig_bg)
    fig.patch.set_edgecolor(edgecolor or fig_bg)
    fig.patch.set_linewidth(0)
    for ax in fig.axes:
        ax.set_facecolor(s['axes.facecolor'])
        ax.tick_params(colors=s['xtick.color'])
        ax.xaxis.label.set_color(s['axes.labelcolor'])
        ax.yaxis.label.set_color(s['axes.labelcolor'])
        ax.title.set_color(s['text.color'])
        for spine in ax.spines.values():
            spine.set_color(s['axes.edgecolor'])
        ax.grid(True, color=s['grid.color'], alpha=s['grid.alpha'])


# ---------------------------------------------------------------------------
# Series palette + titles
# ---------------------------------------------------------------------------
def series_colors() -> list[str]:
    """Return the per-theme multi-series colour palette (re-read at call time)."""
    return list(C.SERIES_COLORS)


_TYPE_LABELS: dict[str | None, str] = {
    None:     'Content',
    'short':  'Shorts',
    'video':  'Videos',
    'stream': 'Streams',
}


def chart_title(verified_only: bool, content_type: str | None, base: str) -> str:
    """Build a chart title from filter state.

    e.g. ``chart_title(True, 'short', 'View Trajectory')`` →
    ``'Verified Shorts — View Trajectory'``.
    """
    type_part = _TYPE_LABELS.get(content_type, 'Content')
    prefix = 'Verified' if verified_only else 'All'
    return f'{prefix} {type_part} — {base}'


# ---------------------------------------------------------------------------
# SQL filter conditions (single source of truth for the in-app charts)
# ---------------------------------------------------------------------------
def build_conditions(*, verified_only: bool, content_type: str | None,
                     time_range: str | None, platform: str | None = None,
                     creator_id: int | None = None,
                     table_prefix: str = 'm.') -> tuple[list[str], list[Any]]:
    """Return ``(conditions, params)`` for the standard media_content filters.

    ``table_prefix`` is ``'m.'`` when the query joins ``creators`` (the global
    timeline) and ``''`` for a single-table query (the per-creator charts).
    ``creator_id`` adds an unprefixed ``creator_id = ?`` scope.
    """
    p = table_prefix
    conditions: list[str] = [f'{p}upload_date != \'\'']
    params: list[Any] = []
    if verified_only:
        conditions.append(f'{p}is_verified = 1')
    ct = content_type
    if ct == 'short':
        conditions.append(f'{p}is_short = 1')
    elif ct == 'video':
        conditions.append(f'{p}is_short = 0')
        conditions.append(f'{p}is_stream = 0')
    elif ct == 'stream':
        conditions.append(f'{p}is_stream = 1')
    if time_range:
        now = datetime.now(timezone.utc)
        if time_range == 'week':
            since: datetime | None = now - timedelta(weeks=1)
        elif time_range == 'month':
            since = now - timedelta(days=30)
        elif time_range == 'year':
            since = now - timedelta(days=365)
        else:
            since = None
        if since:
            conditions.append(f'{p}upload_date >= ?')
            params.append(since.strftime('%Y-%m-%dT%H:%M:%SZ'))
    if platform:
        conditions.append(f'{p}platform = ?')
        params.append(platform)
    if creator_id is not None:
        conditions.append('creator_id = ?')
        params.append(creator_id)
    return conditions, params


# ---------------------------------------------------------------------------
# No-dependency monotone Catmull-Rom → cubic Bézier smoothing
# ---------------------------------------------------------------------------
Segment = tuple[tuple[float, float], tuple[float, float],
                 tuple[float, float], tuple[float, float]]


def smooth_line(xs: Sequence[float], ys: Sequence[float], *,
                 floor: float = 0.0) -> list[Segment]:
    """Return monotone cubic-Bézier segments through ``(xs, ys)``.

    Each segment is a 4-tuple ``(P0, P1, P2, P3)`` of ``(x, y)`` floats —
    ``P0``/``P3`` are the knots, ``P1``/``P2`` the control points.  Returns
    ``[]`` when fewer than two points are supplied (callers fall back to a
    straight ``ax.plot`` / scatter-only rendering).

    Tangents use the Fritsch-Carlson monotone-cubic-Hermite reduction: the
    tangent is flattened to zero at local extrema and clamped so each
    interval stays monotone.  The interpolant therefore never overshoots a
    local minimum, so for view-count data (always ≥ 0) it never dips below
    the data minimum.  As a belt-and-suspenders guard, every control-point y
    is additionally clamped to ``>= floor`` — a cubic is a convex combination
    of its control points, so clamped controls + endpoints ⇒ every sampled
    y ≥ ``floor`` regardless of the tangent maths.
    """
    n = len(xs)
    if n < 2 or n != len(ys):
        return []

    x = [float(v) for v in xs]
    y = [max(floor, float(v)) for v in ys]

    if n == 2:
        p0 = (x[0], y[0])
        p3 = (x[1], y[1])
        # Straight line expressed as a degenerate cubic.
        return [(p0, p0, p3, p3)]

    # Secant slopes per interval.
    d = [0.0] * (n - 1)
    for k in range(n - 1):
        dx = x[k + 1] - x[k]
        d[k] = (y[k + 1] - y[k]) / dx if dx != 0 else 0.0

    # Raw Hermite tangents: average of adjacent secants, flat at extrema.
    t = [0.0] * n
    t[0] = d[0]
    t[n - 1] = d[n - 2]
    for k in range(1, n - 1):
        if d[k - 1] * d[k] <= 0:
            t[k] = 0.0
        else:
            t[k] = (d[k - 1] + d[k]) / 2.0

    # Build segments, applying the per-interval monotone clamp from the raw
    # tangents (order-independent — we never mutate the shared ``t`` array).
    segs: list[Segment] = []
    for k in range(n - 1):
        x0, x1 = x[k], x[k + 1]
        y0, y1 = y[k], y[k + 1]
        dx = x1 - x0
        mk = t[k]
        mk1 = t[k + 1]
        if d[k] == 0:
            mk = 0.0
            mk1 = 0.0
        else:
            alpha = mk / d[k]
            beta = mk1 / d[k]
            s = alpha * alpha + beta * beta
            if s > 9.0:
                tau = 3.0 / (s ** 0.5)
                mk = tau * alpha * d[k]
                mk1 = tau * beta * d[k]
        c1x = x0 + dx / 3.0
        c2x = x1 - dx / 3.0
        c1y = max(floor, y0 + mk * dx / 3.0)
        c2y = max(floor, y1 - mk1 * dx / 3.0)
        segs.append(((x0, y0), (c1x, c1y), (c2x, c2y), (x1, y1)))
    return segs


def smooth_mpl_patch(xs: Sequence[float], ys: Sequence[float], color: str, *,
                     floor: float = 0.0, linewidth: float = 1.5,
                     label: str | None = None, zorder: float = 3.0) -> PathPatch | None:
    """Return a matplotlib ``PathPatch`` drawing the smooth line, or ``None``.

    ``xs`` must be numeric (use ``matplotlib.dates.date2num`` for date axes).
    Returns ``None`` when ``smooth_line`` yields no segments so the caller can
    fall back to a scatter-only plot.
    """
    segs = smooth_line(xs, ys, floor=floor)
    if not segs:
        return None
    verts: list[tuple[float, float]] = [segs[0][0]]
    codes = [Path.MOVETO]
    for _p0, p1, p2, p3 in segs:
        verts.extend([p1, p2, p3])
        codes.extend([Path.CURVE4, Path.CURVE4, Path.CURVE4])
    kwargs: dict[str, Any] = {'fill': False, 'edgecolor': color,
                              'linewidth': linewidth, 'zorder': zorder,
                              'capstyle': 'round', 'joinstyle': 'round'}
    if label is not None:
        kwargs['label'] = label
    return PathPatch(Path(verts, codes), **kwargs)