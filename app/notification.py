"""
Notification service: system tray notifications + audio alerts for download events.
"""
import logging
import subprocess
import platform as _platform

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu

from app.config import Config

logger = logging.getLogger(__name__)

_MAC_SOUNDS = [
    "/System/Library/Sounds/Ping.aiff",
    "/System/Library/Sounds/Glass.aiff",
    "/System/Library/Sounds/Pop.aiff",
]


class NotificationService(QObject):
    """Desktop notifications and system tray management.

    - QSystemTrayIcon for OS-native notification bubbles + tray menu.
    - Plays a system sound via ``afplay`` on macOS.
    - All toggles read from ``Config`` at notify-time (not cached).
    """

    show_window_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = Config()
        self._tray: QSystemTrayIcon | None = None
        self._tray_menu: QMenu | None = None
        self._init_tray()

    def _init_tray(self):
        """Create a system-tray icon with context menu."""
        app = QApplication.instance()
        if app is None:
            return
        try:
            icon = QIcon(":/qfluentwidgets/images/logo.png")
        except Exception:
            icon = app.windowIcon()
        if icon.isNull():
            return

        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("Desktop Downloader")

        # Build context menu
        self._tray_menu = QMenu()
        show_action = QAction("显示/隐藏窗口", self._tray_menu)
        show_action.triggered.connect(self.show_window_requested.emit)
        self._tray_menu.addAction(show_action)

        self._tray_menu.addSeparator()

        quit_action = QAction("退出", self._tray_menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        self._tray_menu.addAction(quit_action)

        self._tray.setContextMenu(self._tray_menu)

        # Double-click restores window
        self._tray.activated.connect(self._on_tray_activated)

        self._tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_window_requested.emit()

    def set_visible_with_tray(self, visible: bool):
        """Show or hide the tray icon."""
        if self._tray is None:
            return
        if visible:
            self._tray.show()
        else:
            self._tray.hide()

    def notify_complete(self, title: str, message: str):
        """Notify the user that a download finished successfully."""
        if not self.config.get("notification_enabled", True):
            return
        self._show_message(title, message, QSystemTrayIcon.Information)
        self._play_sound()

    def notify_error(self, title: str, message: str):
        """Notify the user that a download failed."""
        if not self.config.get("notification_enabled", True):
            return
        self._show_message(title, message, QSystemTrayIcon.Critical)

    def _show_message(self, title: str, body: str, severity):
        if self._tray is None:
            return
        self._tray.showMessage(title, body, severity, 5000)

    def _play_sound(self):
        """Play the configured notification sound (fire-and-forget)."""
        if not self.config.get("notification_sound", True):
            return
        system = _platform.system()
        if system == "Darwin":
            try:
                subprocess.Popen(
                    ["afplay", _MAC_SOUNDS[0]],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                pass
