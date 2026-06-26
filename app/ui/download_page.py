"""
Download list page showing active and completed downloads with progress.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFrame, QWidget,
)

from qfluentwidgets import (
    CardWidget, ProgressBar, PushButton,
    PrimaryPushButton, TitleLabel, CaptionLabel, BodyLabel,
    InfoBar, InfoBarPosition, FluentIcon as FIF,
    HorizontalSeparator, SmoothScrollArea,
)

from app.download_manager import DownloadProgress
from app.utils.helpers import format_size, format_speed, muted_text_color, secondary_text_color, configure_smooth_scroll, open_download_folder


class DownloadItemCard(CardWidget):
    """A single download item card showing progress."""

    pause_clicked = Signal(str)
    retry_clicked = Signal(str)
    remove_clicked = Signal(str)
    open_folder_clicked = Signal(str)

    def __init__(self, task_id: str, filename: str, platform: str = "", parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self._output_file = ""
        self._last_status = ""

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Header row: filename + status
        header_layout = QHBoxLayout()
        self.title_label = BodyLabel(filename[:60])
        # Use QFont instead of stylesheet to preserve BodyLabel's theme-aware color
        _font = QFont()
        _font.setPixelSize(14)
        _font.setWeight(QFont.Weight.Medium)
        self.title_label.setFont(_font)

        self.status_label = BodyLabel("等待中")
        self.status_label.setStyleSheet(f"font-size: 12px; color: {secondary_text_color()};")

        header_layout.addWidget(self.title_label, 1)
        header_layout.addWidget(self.status_label)

        layout.addLayout(header_layout)

        # Platform label
        if platform:
            platform_label = CaptionLabel(platform)
            platform_label.setStyleSheet(f"color: {secondary_text_color()}; font-size: 11px;")
            layout.addWidget(platform_label)

        # Progress bar
        self.progress_bar = ProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(8)
        layout.addWidget(self.progress_bar)

        # Info row: size / speed / percent
        info_layout = QHBoxLayout()
        self.size_label = CaptionLabel("0 B / 0 B")
        self.size_label.setStyleSheet(f"color: {muted_text_color()};")
        self.speed_label = CaptionLabel("---")
        self.speed_label.setStyleSheet(f"color: {muted_text_color()};")
        self.percent_label = CaptionLabel("0%")
        self.percent_label.setStyleSheet(f"color: {muted_text_color()};")

        info_layout.addWidget(self.size_label)
        info_layout.addWidget(self.speed_label)
        info_layout.addStretch()
        info_layout.addWidget(self.percent_label)

        layout.addLayout(info_layout)

        # Action buttons
        btn_layout = QHBoxLayout()
        self.pause_btn = PushButton(FIF.PAUSE, "暂停")
        self.pause_btn.setFixedWidth(80)
        self.pause_btn.clicked.connect(lambda: self.pause_clicked.emit(self.task_id))

        self.retry_btn = PushButton(FIF.SYNC, "重试")
        self.retry_btn.setFixedWidth(80)
        self.retry_btn.setVisible(False)
        self.retry_btn.clicked.connect(lambda: self.retry_clicked.emit(self.task_id))

        self.open_btn = PushButton(FIF.FOLDER, "打开目录")
        self.open_btn.setFixedWidth(100)
        self.open_btn.setVisible(False)
        self.open_btn.clicked.connect(lambda: self.open_folder_clicked.emit(self.task_id))

        self.remove_btn = PushButton(FIF.DELETE, "移除")
        self.remove_btn.setFixedWidth(80)
        self.remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self.task_id))

        btn_layout.addStretch()
        btn_layout.addWidget(self.pause_btn)
        btn_layout.addWidget(self.retry_btn)
        btn_layout.addWidget(self.open_btn)
        btn_layout.addWidget(self.remove_btn)

        layout.addLayout(btn_layout)

    def update_progress(self, progress: DownloadProgress) -> None:
        """Update UI from DownloadProgress data."""
        self.progress_bar.setValue(int(progress.progress_pct))

        if progress._output_file:
            self._output_file = progress._output_file

        downloaded = format_size(progress.downloaded)
        total = format_size(progress.total_size)
        self.size_label.setText(f"{downloaded} / {total}")
        self.speed_label.setText(format_speed(progress.speed))
        self.percent_label.setText(f"{progress.progress_pct:.1f}%")

        # Only update stylesheets and visibility when status changes
        status = progress.status
        if status == self._last_status:
            return
        self._last_status = status

        status_map = {
            "pending": "等待中",
            "downloading": "下载中",
            "paused": "已暂停",
            "completed": "已完成",
            "error": "下载失败",
            "merging": "正在合并音视频...",
        }
        self.status_label.setText(status_map.get(status, status))

        if status == "error":
            self.status_label.setStyleSheet("font-size: 12px; color: #e74c3c;")
            self.progress_bar.setCustomBarColor(QColor(231, 76, 60), QColor(192, 57, 43))
            self.pause_btn.setVisible(False)
            self.retry_btn.setVisible(True)
        elif status == "completed":
            self.status_label.setStyleSheet("font-size: 12px; color: #27ae60;")
            self.pause_btn.setVisible(False)
            self.retry_btn.setVisible(False)
            self.open_btn.setVisible(True)
        elif status == "paused":
            self.status_label.setStyleSheet("font-size: 12px; color: #f39c12;")
            self.pause_btn.setText("继续")
        elif status == "downloading":
            self.status_label.setStyleSheet("font-size: 12px; color: #3498db;")
            self.pause_btn.setText("暂停")
            self.pause_btn.setVisible(True)
        elif status == "merging":
            self.status_label.setStyleSheet("font-size: 12px; color: #9b59b6;")


class DownloadPage(SmoothScrollArea):
    """Page showing all download tasks."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: dict[str, DownloadItemCard] = {}

        self._setup_ui()
        configure_smooth_scroll(self)

    def _setup_ui(self) -> None:
        """Build the download page UI."""
        self.container = QFrame(self)
        self.container.setObjectName("downloadContainer")
        self.setWidget(self.container)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        self.vBoxLayout = QVBoxLayout(self.container)
        self.vBoxLayout.setContentsMargins(40, 20, 40, 20)
        self.vBoxLayout.setSpacing(16)

        # Header
        header = TitleLabel("下载列表")
        header.setStyleSheet("font-size: 28px; font-weight: 600;")
        self.vBoxLayout.addWidget(header)

        self.desc_label = CaptionLabel("暂无下载任务")
        self.desc_label.setStyleSheet(f"font-size: 14px; color: {muted_text_color()};")
        self.vBoxLayout.addWidget(self.desc_label)

        # Separator
        self.vBoxLayout.addWidget(HorizontalSeparator())

        toolbar_layout = QHBoxLayout()
        self.stop_all_btn = PushButton(FIF.CANCEL, "全部停止")
        self.stop_all_btn.clicked.connect(self._on_stop_all)
        self.cancel_all_btn = PushButton(FIF.DELETE, "全部取消")
        self.cancel_all_btn.clicked.connect(self._on_cancel_all)
        self.start_all_btn = PrimaryPushButton(FIF.PLAY, "全部开始")
        self.start_all_btn.clicked.connect(self._on_start_all)
        toolbar_layout.addWidget(self.stop_all_btn)
        toolbar_layout.addWidget(self.cancel_all_btn)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(self.start_all_btn)
        self.vBoxLayout.addLayout(toolbar_layout)

        # Cards container
        self.cards_layout = QVBoxLayout()
        self.cards_layout.setSpacing(10)
        self.vBoxLayout.addLayout(self.cards_layout)

        self.vBoxLayout.addStretch()

    def add_card(self, task_id: str, filename: str, platform: str = "") -> None:
        """Add a new download item card."""
        card = DownloadItemCard(task_id, filename, platform)
        card.pause_clicked.connect(self._on_pause)
        card.retry_clicked.connect(self._on_retry)
        card.remove_clicked.connect(self._on_remove)
        card.open_folder_clicked.connect(self._on_open_folder)

        self._cards[task_id] = card
        self.cards_layout.addWidget(card)
        self.desc_label.hide()

    def update_progress(self, progress: DownloadProgress) -> None:
        """Update progress for a task (called from DownloadManager)."""
        if progress.task_id not in self._cards:
            # First time seeing this task - add card
            self.add_card(
                progress.task_id,
                progress.filename,
                getattr(progress, '_platform', ''),
            )

        card = self._cards.get(progress.task_id)
        if card:
            card.update_progress(progress)

    def on_download_completed(self, progress: DownloadProgress) -> None:
        """Called when a download completes."""
        card = self._cards.get(progress.task_id)
        if card:
            card.update_progress(progress)

        InfoBar.success(
            title="下载完成",
            content=f"{progress.filename} 下载完成",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=5000,
            parent=self.window(),
        )

    def on_download_error(self, progress: DownloadProgress) -> None:
        """Called when a download errors."""
        card = self._cards.get(progress.task_id)
        if card:
            card.update_progress(progress)

        InfoBar.error(
            title="下载失败",
            content=f"{progress.filename}: {progress.error_msg[:50]}",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=8000,
            parent=self.window(),
        )

    def _on_pause(self, task_id: str) -> None:
        """Handle pause/resume."""
        mw = self.window()
        if hasattr(mw, 'download_manager'):
            mw.download_manager.pause_task(task_id)

    def _on_retry(self, task_id: str) -> None:
        """Re-queue a failed download task."""
        mw = self.window()
        if not hasattr(mw, 'download_manager'):
            return
        dm = mw.download_manager
        completed = dm.get_completed()
        for p in completed:
            if p.task_id == task_id:
                task = getattr(p, '_task', None)
                if task:
                    dm.add_task(task)
                    InfoBar.info(
                        title="已重试", content="下载任务已重新加入队列",
                        orient=Qt.Horizontal, isClosable=True,
                        position=InfoBarPosition.TOP_RIGHT, duration=3000,
                        parent=self.window(),
                    )
                break

    def _on_open_folder(self, task_id: str) -> None:
        """Open the folder containing the downloaded file."""
        card = self._cards.get(task_id)
        if card and card._output_file:
            open_download_folder(card._output_file)

    def on_task_added(self, tid: str, filename: str, platform: str) -> None:
        """Create a pre-waiting card when a task is queued."""
        if tid not in self._cards:
            self.add_card(tid, filename, platform)

    def _on_stop_all(self) -> None:
        mw = self.window()
        if hasattr(mw, 'download_manager'):
            mw.download_manager.stop_all()

    def _on_cancel_all(self) -> None:
        mw = self.window()
        if hasattr(mw, 'download_manager'):
            mw.download_manager.cancel_all()
        for tid in list(self._cards.keys()):
            card = self._cards.pop(tid)
            self.cards_layout.removeWidget(card)
            card.deleteLater()
        if not self._cards:
            self.desc_label.show()

    def _on_start_all(self) -> None:
        mw = self.window()
        if hasattr(mw, 'download_manager'):
            mw.download_manager.resume_all()

    def _on_remove(self, task_id: str) -> None:
        """Handle remove card."""
        mw = self.window()
        if hasattr(mw, 'download_manager'):
            mw.download_manager.remove_task(task_id)
        if task_id in self._cards:
            card = self._cards.pop(task_id)
            self.cards_layout.removeWidget(card)
            card.deleteLater()
            if not self._cards:
                self.desc_label.show()
