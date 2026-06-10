from __future__ import annotations
import os
import sys
from pathlib import Path
def _app_data_dir() -> Path:
    """Return the platform-appropriate data directory for Kleos.\n\nWindows: %APPDATA%\\.kleos\nOthers:  ~/.kleos\n"""
    if sys.platform == 'win32':
        base = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
        return base / '.kleos'
    else:
        base = Path.home()
        return base / '.kleos'
APP_DIR: Path = _app_data_dir()
STORAGE_DIR: Path = APP_DIR / 'storage'
BACKUPS_DIR: Path = APP_DIR / 'storage' / 'backups'
THUMBNAILS_DIR: Path = APP_DIR / 'cache' / 'thumbnails'