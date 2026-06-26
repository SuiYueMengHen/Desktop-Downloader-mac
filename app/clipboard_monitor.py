"""
Clipboard monitor - watches clipboard for Bilibili video URLs.
Uses QTimer to poll clipboard text periodically and emits a signal when a
supported video URL is detected (with dedup).
"""
import logging
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QClipboard
from PySide6.QtWidgets import QApplication

from app.utils.helpers import detect_platform

logger = logging.getLogger(__name__)


class ClipboardMonitor(QObject):
    """Monitors clipboard for video URLs and emits a signal when found."""

    url_detected = Signal(str)  # emits the detected URL

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(1200)  # check every 1.2s
        self._timer.timeout.connect(self._check_clipboard)
        self._last_url = ""  # dedup
        self._enabled = False

    @property
    def is_running(self) -> bool:
        return self._timer.isActive()

    def start(self):
        self._last_url = self._get_clipboard_text()
        self._enabled = True
        if not self._timer.isActive():
            self._timer.start()

    def stop(self):
        self._enabled = False
        if self._timer.isActive():
            self._timer.stop()

    def set_enabled(self, enabled: bool):
        if enabled and not self._enabled:
            self.start()
        elif not enabled and self._enabled:
            self.stop()

    def _get_clipboard_text(self) -> str:
        try:
            app = QApplication.instance()
            if not app:
                return ""
            clip = app.clipboard()
            if clip:
                text = clip.text(mode=QClipboard.Clipboard)
                return (text or "").strip()
        except RuntimeError:
            # Qt C++ wrapper may be deleted during shutdown
            return ""
        return ""

    def _check_clipboard(self):
        if not self._enabled:
            return
        try:
            text = self._get_clipboard_text()
            if not text or text == self._last_url:
                return

            # Check if it's a supported platform URL
            platform = detect_platform(text)
            if platform:
                self._last_url = text
                self.url_detected.emit(text)
            else:
                # Only update last_url for non-empty texts to avoid
                # re-triggering on the same URL when user copies other stuff
                self._last_url = text
        except RuntimeError:
            logger.warning("Clipboard access failed (shutdown?)", exc_info=True)
