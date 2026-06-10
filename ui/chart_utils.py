"""Interactive chart utilities for Kleos.

Provides ``_ZoomableFigureCanvas``, a mixin that adds scroll-to-zoom,
click-drag-pan, and double-click-reset to any ``FigureCanvas`` subclass.
"""
from __future__ import annotations

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from PyQt6.QtCore import QPoint, Qt


# Scale factor applied per scroll-step: 1.15 means each tick zooms ~15 %.
_ZOOM_FACTOR = 1.15


class _ZoomableFigureCanvas:
    """Mixin for ``FigureCanvas`` that adds interactive zoom and pan.

    Behaviour
    ---------
    - **Scroll**: zooms both axes around the mouse-cursor position.
      Scroll-up zooms in, scroll-down zooms out.
    - **Left-click drag**: pans both axes.
    - **Double-click**: resets to the default (home) view.
    - Filter / data changes that call ``_render()`` automatically reset
      the view because ``_save_home_limits()`` is invoked at the end of
      every render cycle.

    Subclass contract
    -----------------
    The mixed-in class **must** call ``_save_home_limits()`` at the end of
    its ``_render()`` method (after ``draw()``) so the mixin knows the
    default axis range to reset to.
    """

    # -- home limits ----------------------------------------------------------

    def _save_home_limits(self) -> None:
        """Snapshot the current axis limits as the "home" view.

        Call this at the end of ``_render()`` **after** ``draw()`` so the
        mixin always has the correct baseline to reset to.
        """
        ax = self._primary_axes()
        if ax is not None:
            self._home_xlim = ax.get_xlim()
            self._home_ylim = ax.get_ylim()
        else:
            self._home_xlim = None
            self._home_ylim = None

    def _reset_to_home(self) -> None:
        """Restore the saved home limits and redraw."""
        ax = self._primary_axes()
        if ax is None or self._home_xlim is None:
            return
        ax.set_xlim(self._home_xlim)
        ax.set_ylim(self._home_ylim)
        self.draw()

    # -- helpers --------------------------------------------------------------

    def _primary_axes(self):
        """Return the first (primary) Axes of the figure, or None."""
        axes = getattr(self, '_fig', None)
        if axes is not None:
            fig_axes = axes.axes
            if fig_axes:
                return fig_axes[0]
        return None

    def _axes_at(self, pos: QPoint):
        """Return the matplotlib Axes under *pos* (widget coords), or None."""
        ax = self._primary_axes()
        if ax is None:
            return None
        # Convert Qt widget position → matplotlib display coords.
        dpi_ratio = self.devicePixelRatioF()
        x = pos.x() * dpi_ratio
        y = (self.height() - pos.y()) * dpi_ratio
        if ax.contains_point((x, y)):
            return ax
        return None

    # -- Qt event overrides ---------------------------------------------------

    def wheelEvent(self, event) -> None:  # noqa: N802
        """Zoom both axes around the cursor position."""
        ax = self._axes_at(event.position().toPoint() if hasattr(event, 'position') else event.pos())
        if ax is None:
            super().wheelEvent(event)
            return

        # Determine zoom direction: positive angleDelta → zoom in.
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        factor = _ZOOM_FACTOR if delta > 0 else 1.0 / _ZOOM_FACTOR

        # Cursor position in data coordinates.
        dpi_ratio = self.devicePixelRatioF()
        qt_pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        mx = qt_pos.x() * dpi_ratio
        my = (self.height() - qt_pos.y()) * dpi_ratio
        cursor_data = ax.transData.inverted().transform((mx, my))

        # Shrink each axis range toward the cursor.
        for getter, setter, cursor_val, clamp_lo in [
            (ax.get_xlim, ax.set_xlim, cursor_data[0], None),
            (ax.get_ylim, ax.set_ylim, cursor_data[1], 0),
        ]:
            lo, hi = getter()
            span = hi - lo
            if span <= 0:
                continue
            new_span = span / factor
            ratio = (cursor_val - lo) / span  # where cursor sits in [0, 1]
            new_lo = cursor_val - ratio * new_span
            new_hi = new_lo + new_span
            if clamp_lo is not None and new_lo < clamp_lo:
                new_hi += clamp_lo - new_lo
                new_lo = clamp_lo
            setter(new_lo, new_hi)

        self.draw()
        event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """Begin a pan on left-click over the chart area."""
        if event.button() == Qt.MouseButton.LeftButton:
            ax = self._axes_at(event.position().toPoint() if hasattr(event, 'position') else event.pos())
            if ax is not None:
                self._pan_active = True
                self._pan_start = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                self._pan_xlim = ax.get_xlim()
                self._pan_ylim = ax.get_ylim()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        """Pan the chart as the user drags."""
        if getattr(self, '_pan_active', False):
            ax = self._primary_axes()
            if ax is None:
                return
            cur = event.position().toPoint() if hasattr(event, 'position') else event.pos()
            dx = cur.x() - self._pan_start.x()
            dy = cur.y() - self._pan_start.y()
            # Convert pixel delta to data delta via the transform.
            dpi_ratio = self.devicePixelRatioF()
            p0 = (self._pan_start.x() * dpi_ratio, (self.height() - self._pan_start.y()) * dpi_ratio)
            p1 = ((self._pan_start.x() + dx) * dpi_ratio, (self.height() - self._pan_start.y() - dy) * dpi_ratio)
            inv = ax.transData.inverted()
            d0 = inv.transform(p0)
            d1 = inv.transform(p1)
            data_dx = d1[0] - d0[0]
            data_dy = d1[1] - d0[1]
            new_ylo = self._pan_ylim[0] - data_dy
            new_yhi = self._pan_ylim[1] - data_dy
            # Clamp: y-axis (view count) must never dip below 0.
            if new_ylo < 0:
                new_yhi -= new_ylo
                new_ylo = 0
            ax.set_xlim(self._pan_xlim[0] - data_dx, self._pan_xlim[1] - data_dx)
            ax.set_ylim(new_ylo, new_yhi)
            self.draw()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        """End the pan."""
        if event.button() == Qt.MouseButton.LeftButton and getattr(self, '_pan_active', False):
            self._pan_active = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        """Reset the chart to its home (default) view."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._reset_to_home()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)