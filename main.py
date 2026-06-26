#!/usr/bin/env python3
"""
Desktop Downloader - Multi-platform video downloader with Fluent Design UI.
Supports Bilibili video downloading.

Usage:
    python main.py
"""
import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont


_CONFIG_DIR = Path.home() / ".desktop-downloader"
_CRASH_MARKER = _CONFIG_DIR / ".running"


def _setup_file_logging():
    """Configure root logger to write to ~/.desktop-downloader/app.log."""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = _CONFIG_DIR / "app.log"
    fh = logging.FileHandler(log_file, encoding="utf-8", delay=True)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    logging.info("=== App started ===")


def main():
    """Application entry point."""
    # Log to file: ~/.desktop-downloader/app.log
    _setup_file_logging()

    # Crash recovery detection
    _crashed = _CRASH_MARKER.exists()
    if _crashed:
        logging.warning("Previous run did not shut down cleanly — possible crash")
    # Write marker now; remove on clean exit
    _CRASH_MARKER.touch()

    # High-DPI support (auto in Qt6)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # Create application
    app = QApplication(sys.argv)
    app.setApplicationName("Desktop Downloader")
    app.setOrganizationName("DesktopDownloader")
    from app import __version__
    app.setApplicationVersion(__version__)

    import platform
    import traceback
    # Set application font based on platform
    font_name = "PingFang SC" if platform.system() == "Darwin" else "Microsoft YaHei UI"
    font = QFont(font_name, 9)
    app.setFont(font)

    # Override qfluentwidgets default font families to avoid "Segoe UI" warning on macOS
    from qfluentwidgets import setFontFamilies, isDarkTheme
    if platform.system() == "Darwin":
        setFontFamilies(['PingFang SC', 'Microsoft YaHei', 'Segoe UI'])
    else:
        setFontFamilies(['Microsoft YaHei UI', 'Segoe UI', 'PingFang SC'])

    if isDarkTheme():
        app.setStyleSheet("""
            QToolTip {
                background-color: #2d2d2d;
                color: white;
                border: 1px solid #555;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 12px;
            }
        """)
    else:
        app.setStyleSheet("""
            QToolTip {
                background-color: #f0f0f0;
                color: #333;
                border: 1px solid #ccc;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 12px;
            }
        """)

    # Global exception hook: log to file + terminal, attempt page recovery
    _main_window_ref = [None]

    def _global_excepthook(exc_type, exc_value, exc_tb):
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.critical("Unhandled exception:\n%s", tb_text)
        print(tb_text, file=sys.stderr, flush=True)
        # Attempt to reset the current page to idle state
        mw = _main_window_ref[0]
        if mw is not None:
            try:
                current = mw.stackedWidget.currentWidget()
                if hasattr(current, 'reset_to_idle'):
                    current.reset_to_idle()
            except Exception:
                pass  # recovery must never throw

    sys.excepthook = _global_excepthook

    # Import here to avoid circular imports
    from app.main_window import MainWindow

    # Create and show main window
    window = MainWindow(was_crashed=_crashed)
    _main_window_ref[0] = window
    window.show()

    # Remove crash marker + flush logs on clean exit
    def _on_clean_exit():
        _CRASH_MARKER.unlink(missing_ok=True)
        logging.shutdown()

    app.aboutToQuit.connect(_on_clean_exit)

    # Qt event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
