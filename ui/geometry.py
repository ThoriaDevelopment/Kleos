"""Save/restore window geometry across sessions.

Geometry is persisted as a base64 blob of Qt's ``saveGeometry()`` byte array.
The main window stores to the *global* settings file (so its size/position
survive a profile switch); dialogs store to the *per-profile* database so
each profile remembers its own dialog layouts.

Keys are namespaced ``geom.<key>``.  Dialogs hook their ``finished`` signal
(emitted on accept, reject, and window-manager close) so every exit path is
captured with a single connection.
"""
from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import QByteArray
from PyQt6.QtWidgets import QWidget

from core.db_manager import DatabaseManager


def save_geometry(widget: QWidget, key: str, db: DatabaseManager, *,
                  global_store: bool = False) -> None:
    """Persist ``widget``'s geometry under ``key`` (namespaced ``geom.<...>``).

    ``global_store=True`` writes to the global settings file; otherwise to the
    per-profile settings table.
    """
    if sip.isdeleted(widget):
        return
    blob = bytes(widget.saveGeometry().toBase64()).decode('ascii')
    full_key = f'geom.{key}'
    if global_store:
        db.set_global_setting(full_key, blob)
    else:
        db.set_setting(full_key, blob)


def restore_geometry(widget: QWidget, key: str, db: DatabaseManager, *,
                     global_store: bool = False) -> bool:
    """Restore ``widget``'s geometry from ``key``.

    Returns ``True`` if a saved geometry was applied, ``False`` otherwise (in
    which case the widget keeps whatever size/position it already has).
    """
    full_key = f'geom.{key}'
    blob = db.get_global_setting(full_key) if global_store else db.get_setting(full_key)
    if not blob:
        return False
    ba = QByteArray.fromBase64(blob.encode('ascii'))
    return widget.restoreGeometry(ba)


def fit_to_layout_minimum(widget: QWidget) -> None:
    """Grow ``widget``'s height to at least its layout's minimum for its width.

    A saved geometry from an older layout (fewer or smaller rows) can be
    shorter than the current content's minimum height.  ``restore_geometry``
    runs before the layout is built, so it applies the stale short height
    without complaint; then the layout raises the minimum, and on show Qt on
    Windows logs ``QWindowsWindow::setGeometry: Unable to set geometry …`` as
    it snaps the window up to the real minimum.

    Call this once the layout is fully built (after ``restore_geometry`` and
    after the content rows are added).  It keeps the saved width/position and
    only bumps the height to ``layout.minimumHeightForWidth(width)``, so the
    dialog is never shown shorter than its contents and the warning never
    fires.
    """
    if sip.isdeleted(widget):
        return
    lay = widget.layout()
    if lay is None:
        return
    need_h = lay.minimumHeightForWidth(widget.width())
    if need_h > 0 and widget.height() < need_h:
        widget.resize(widget.width(), need_h)