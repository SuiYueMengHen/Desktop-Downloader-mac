"""
FluentUI-style startup splash overlay with dark/light mode support.
Appears briefly during initialization, then fades out.
"""
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGraphicsOpacityEffect

from qfluentwidgets import (
    CaptionLabel, StrongBodyLabel, ProgressRing,
    FluentIcon as FIF, isDarkTheme,
)

from app import __version__
from app.utils.helpers import muted_text_color


class SplashOverlay(QWidget):
    """FluentUI startup splash overlay that covers the main window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("splashOverlay")

        if parent:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)

        self._fade_anim = None
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._setup_ui()
        self._start_progress_animation()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(12)

        icon_label = StrongBodyLabel("")
        icon_label.setPixmap(FIF.DOWNLOAD.icon().pixmap(64, 64))
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label)

        title_label = StrongBodyLabel("Desktop Downloader")
        title_label.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPixelSize(26)
        title_font.setWeight(QFont.Weight.DemiBold)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        version_label = CaptionLabel(f"v{__version__}")
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setStyleSheet(f"color: {muted_text_color()}; font-size: 13px;")
        layout.addWidget(version_label)

        layout.addSpacing(8)

        self.progress_ring = ProgressRing()
        self.progress_ring.setFixedSize(48, 48)
        self.progress_ring.setStrokeWidth(4)
        layout.addWidget(self.progress_ring, 0, Qt.AlignCenter)

        self.status_label = CaptionLabel("正在启动...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet(f"color: {muted_text_color()}; font-size: 13px;")
        layout.addWidget(self.status_label)

    def _start_progress_animation(self):
        self._progress_value = 0
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(30)
        self._progress_timer.timeout.connect(self._spin_progress)
        self._progress_timer.start()

    def _spin_progress(self):
        self._progress_value = (self._progress_value + 3) % 101
        self.progress_ring.setValue(self._progress_value)

    def set_status(self, text: str):
        self.status_label.setText(text)

    def dismiss(self, callback=None):
        self._progress_timer.stop()
        self.progress_ring.setValue(100)
        if callback:
            QTimer.singleShot(200, callback)
        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_anim.setDuration(400)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_anim.finished.connect(self.close)
        self._fade_anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        alpha = int(248 * self._opacity_effect.opacity())
        if isDarkTheme():
            bg = QColor(32, 32, 32, min(alpha, 240))
        else:
            bg = QColor(248, 248, 248, min(alpha, 240))
        painter.setBrush(bg)
        painter.setPen(Qt.NoPen)
        painter.drawRect(self.rect())

    def resizeEvent(self, event):
        if self.parent():
            self.setGeometry(self.parent().rect())
        super().resizeEvent(event)
