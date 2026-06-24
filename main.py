#!/usr/bin/env python3
"""
Desktop Downloader - Multi-platform video downloader with Fluent Design UI.
Supports Bilibili, Douyin, TikTok and more.

Usage:
    python main.py
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont


def main():
    """Application entry point."""
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
    from qfluentwidgets import setFontFamilies
    if platform.system() == "Darwin":
        setFontFamilies(['PingFang SC', 'Microsoft YaHei', 'Segoe UI'])
    else:
        setFontFamilies(['Microsoft YaHei UI', 'Segoe UI', 'PingFang SC'])

    # Application-wide tooltip style
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

    # Global exception hook: log to terminal and attempt page recovery
    _main_window_ref = [None]  # mutable holder for closure

    def _global_excepthook(exc_type, exc_value, exc_tb):
        print(f"[UNHANDLED {exc_type.__name__}] {exc_value}", file=sys.stderr, flush=True)
        traceback.print_exception(exc_type, exc_value, exc_tb, file=sys.stderr)
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
    window = MainWindow()
    _main_window_ref[0] = window
    window.show()

    # Qt event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
