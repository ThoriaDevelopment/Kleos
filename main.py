import sys
from PyQt6.QtWidgets import QApplication
from core.db_manager import DatabaseManager
from core.paths import APP_DIR, BACKUPS_DIR, STORAGE_DIR, THUMBNAILS_DIR
from ui.main_window import MainWindow
from ui.theme import build_global_qss
def _enable_dwm_dark_title_bar(window) -> None:
    """Force the Windows native title bar to dark mode via DWM API."""
    if sys.platform!= 'win32':
        return None
    else:
        import ctypes
        hwnd = int(window.winId())
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value))
def initialize_app_data() -> None:
    """Ensure the %APPDATA%\\.kleos directory tree exists."""
    for d in [APP_DIR, STORAGE_DIR, BACKUPS_DIR, THUMBNAILS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
def main() -> None:
    initialize_app_data()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(build_global_qss())
    db = DatabaseManager('default')
    window = MainWindow(db)
    _enable_dwm_dark_title_bar(window)
    window.show()
    sys.exit(app.exec())
if __name__ == '__main__':
    main()