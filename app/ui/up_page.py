"""
UP主 space page - browse uploader info and paginated video list.
"""
from typing import Optional

from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFrame, QWidget, QGridLayout, QLabel,
    QStackedWidget,
)

from qfluentwidgets import (
    SearchLineEdit, PushButton, PrimaryPushButton,
    CardWidget, CaptionLabel, BodyLabel, StrongBodyLabel,
    InfoBar, InfoBarPosition, FluentIcon as FIF,
    ImageLabel, TitleLabel, HorizontalSeparator, ProgressRing,
    SimpleCardWidget, SmoothScrollArea,
)

from app.utils.cover_loader import CoverLoader
from app.utils.async_worker import AsyncWorker
from app.utils.worker_mixin import WorkerMixin
from app.utils.helpers import format_duration, format_size, sanitize_filename, muted_text_color, secondary_text_color, normal_text_color, configure_smooth_scroll
from app.platforms.bilibili import BilibiliPlatform, extract_uid


PAGE_SIZE = 30


class UpInfoWorker(AsyncWorker):
    """Fetch uploader info in background thread."""
    def __init__(self, platform: BilibiliPlatform, uid: int):
        super().__init__()
        self.platform = platform
        self.uid = uid

    async def work(self):
        return await self.platform.get_uploader_info(self.uid)


class UpVideosWorker(AsyncWorker):
    """Fetch paginated video list in background thread."""
    def __init__(self, platform: BilibiliPlatform, uid: int, page: int = 1, page_size: int = PAGE_SIZE):
        super().__init__()
        self.platform = platform
        self.uid = uid
        self.page = page
        self.page_size = page_size

    async def work(self):
        return await self.platform.get_uploader_videos(self.uid, self.page, self.page_size)


def format_count(n: int) -> str:
    """Format large numbers: 1234 -> 1234, 12345 -> 1.2万"""
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return str(n)


class VideoCard(CardWidget):
    """A single video card in the grid."""

    parse_clicked = Signal(str)  # bvid

    def __init__(self, video: dict, parent=None):
        super().__init__(parent)
        self._video = video
        self._bvid = video.get("bvid", "")
        self._cover_data: Optional[bytes] = None
        self.setFixedWidth(280)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # Cover image
        self.cover_label = ImageLabel()
        self.cover_label.setFixedSize(260, 146)
        self.cover_label.setBorderRadius(6, 6, 6, 6)
        self.cover_label.setScaledContents(True)
        layout.addWidget(self.cover_label)

        # Title
        title = video.get("title", "无标题")
        self.title_label = BodyLabel(title[:50])
        self.title_label.setToolTip(title)
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(f"font-size: 13px; color: {normal_text_color()};")
        layout.addWidget(self.title_label)

        # Meta row
        duration = video.get("duration", 0)
        play = format_count(video.get("play", 0))
        meta = CaptionLabel(f"{play}次播放 · {format_duration(duration)}")
        meta.setStyleSheet(f"color: {muted_text_color()}; font-size: 11px;")
        layout.addWidget(meta)

        # Parse button
        self.parse_btn = PushButton(FIF.SEARCH, "解析下载")
        self.parse_btn.setFixedHeight(32)
        self.parse_btn.clicked.connect(lambda: self.parse_clicked.emit(self._bvid))
        layout.addWidget(self.parse_btn)

    def set_cover(self, data: bytes):
        self._cover_data = data
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            scaled = pixmap.scaled(260, 146, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.cover_label.setPixmap(scaled)


class UpPage(SmoothScrollArea, WorkerMixin):
    """UP主 space page - browse uploader info and videos."""

    parse_video = Signal(str)  # emits bilibili video URL

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._platform: Optional[BilibiliPlatform] = None
        self._current_uid: Optional[int] = None
        self._current_page: int = 1
        self._expected_page: int = 1
        self._total_videos: int = 0
        self._videos_data: list[dict] = []
        self._video_cards: list[VideoCard] = []
        self._loading = False
        self._progress_value = 0
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(33)
        self._progress_timer.timeout.connect(self._spin_progress)

        self._setup_ui()
        self._load_cancelled = False
        WorkerMixin.__init_from__(self)
        configure_smooth_scroll(self)

    def _init_platform(self):
        if self.main_window and hasattr(self.main_window, 'bilibili'):
            self._platform = self.main_window.bilibili
        else:
            from app.platforms.bilibili import BilibiliPlatform
            self._platform = BilibiliPlatform()

    def _setup_ui(self):
        self.container = QFrame(self)
        self.container.setObjectName("upContainer")
        self.setWidget(self.container)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        self.vBoxLayout = QVBoxLayout(self.container)
        self.vBoxLayout.setContentsMargins(40, 20, 40, 20)
        self.vBoxLayout.setSpacing(16)

        # Header
        header = TitleLabel("UP主空间")
        header.setStyleSheet("font-size: 28px; font-weight: 600;")
        self.vBoxLayout.addWidget(header)

        desc = CaptionLabel("粘贴UP主空间链接，查看视频列表并选择下载")
        desc.setStyleSheet(f"font-size: 14px; color: {muted_text_color()};")
        self.vBoxLayout.addWidget(desc)

        # URL Input
        url_card = CardWidget(self.container)
        url_layout = QHBoxLayout(url_card)
        self.url_input = SearchLineEdit()
        self.url_input.setPlaceholderText("粘贴UP主空间链接，如 https://space.bilibili.com/23084818")
        self.url_input.setMinimumHeight(40)
        self.url_input.setClearButtonEnabled(True)
        self.url_input.searchSignal.connect(self._on_load_up)

        self.load_btn = PrimaryPushButton(FIF.SEARCH, "查看")
        self.load_btn.setMinimumHeight(40)
        self.load_btn.clicked.connect(self._on_load_up)

        url_layout.addWidget(self.url_input, 1)
        url_layout.addWidget(self.load_btn)
        self.vBoxLayout.addWidget(url_card)

        # Status
        self.status_label = CaptionLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.hide()
        self.vBoxLayout.addWidget(self.status_label)

        # ── Uploader Info Card (hidden until data loaded) ──
        self.info_card = CardWidget(self.container)
        self.info_card.setVisible(False)
        info_layout = QHBoxLayout(self.info_card)

        self.avatar_label = ImageLabel()
        self.avatar_label.setFixedSize(72, 72)
        self.avatar_label.setBorderRadius(36, 36, 36, 36)
        self.avatar_label.setScaledContents(True)

        info_text = QVBoxLayout()
        self.up_name = TitleLabel("")
        self.up_name.setStyleSheet("font-size: 20px;")
        self.up_sign = CaptionLabel("")
        self.up_sign.setStyleSheet(f"color: {muted_text_color()}; font-size: 13px;")
        self.up_stats = CaptionLabel("")
        self.up_stats.setStyleSheet(f"color: {secondary_text_color()}; font-size: 12px;")

        info_text.addWidget(self.up_name)
        info_text.addWidget(self.up_sign)
        info_text.addWidget(self.up_stats)
        info_text.addStretch()

        info_layout.addWidget(self.avatar_label)
        info_layout.addLayout(info_text, 1)
        self.vBoxLayout.addWidget(self.info_card)

        self.vBoxLayout.addWidget(HorizontalSeparator())

        # ── Content Stack (empty ↔ loading ↔ grid, zero layout shift) ──
        self.content_stack = QStackedWidget()

        # Page 0: Empty (initial state, no URL loaded)
        self.empty_page = QWidget()
        ep_layout = QVBoxLayout(self.empty_page)
        ep_layout.setAlignment(Qt.AlignCenter)
        self.empty_hint = CaptionLabel("在上方输入UP主空间链接后点击「查看」")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setStyleSheet(f"color: {secondary_text_color()}; font-size: 14px;")
        ep_layout.addWidget(self.empty_hint)
        self.content_stack.addWidget(self.empty_page)

        # Page 1: Loading indicator (ProgressRing)
        self.loading_page = QWidget()
        lp_layout = QVBoxLayout(self.loading_page)
        lp_layout.setAlignment(Qt.AlignCenter)
        lp_layout.setContentsMargins(0, 40, 0, 40)

        self.progress_ring = ProgressRing()
        self.progress_ring.setFixedSize(60, 60)
        self.progress_ring.setStrokeWidth(6)

        self.loading_text = CaptionLabel("正在获取UP主信息...")
        self.loading_text.setAlignment(Qt.AlignCenter)
        self.loading_text.setStyleSheet(f"color: {muted_text_color()}; font-size: 14px;")

        lp_layout.addWidget(self.progress_ring, 0, Qt.AlignCenter)
        lp_layout.addSpacing(12)
        lp_layout.addWidget(self.loading_text, 0, Qt.AlignCenter)
        self.content_stack.addWidget(self.loading_page)

        # Page 2: Content (grid + load more)
        self.content_page = QWidget()
        cp_layout = QVBoxLayout(self.content_page)
        cp_layout.setContentsMargins(0, 0, 0, 0)
        cp_layout.setSpacing(16)

        self.grid_label = StrongBodyLabel("视频列表")
        self.grid_label.setStyleSheet("font-size: 16px;")
        cp_layout.addWidget(self.grid_label)

        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(12)
        cp_layout.addWidget(self.grid_widget)

        # Load more (button + small progress ring)
        self.load_more_container = QWidget()
        load_more_layout = QHBoxLayout(self.load_more_container)
        load_more_layout.setAlignment(Qt.AlignCenter)
        load_more_layout.setSpacing(8)

        self.load_more_ring = ProgressRing()
        self.load_more_ring.setFixedSize(24, 24)
        self.load_more_ring.setStrokeWidth(3)
        self.load_more_ring.setVisible(False)

        self.load_more_btn = PushButton(FIF.SYNC, "加载更多")
        self.load_more_btn.setFixedHeight(40)
        self.load_more_btn.clicked.connect(self._on_load_more)

        load_more_layout.addWidget(self.load_more_ring)
        load_more_layout.addWidget(self.load_more_btn)
        cp_layout.addWidget(self.load_more_container, 0, Qt.AlignCenter)

        cp_layout.addStretch()
        self.content_stack.addWidget(self.content_page)

        self.content_stack.setCurrentIndex(0)
        self.vBoxLayout.addWidget(self.content_stack)

        self.vBoxLayout.addStretch()

    def _spin_progress(self):
        # Loop 0→100→0→100... for indeterminate progress animation
        self._progress_value = (self._progress_value + 4) % 101
        self.progress_ring.setValue(self._progress_value)
        self.load_more_ring.setValue(self._progress_value)

    def _show_loading(self, text: str):
        self.status_label.hide()
        self.loading_text.setText(text)
        self.content_stack.setCurrentIndex(1)
        self._progress_value = 0
        self._progress_timer.start()

    def _hide_loading(self):
        """Stop the spinning timer."""
        self._progress_timer.stop()
        self.progress_ring.setValue(0)
        self.load_more_ring.setValue(0)

    def _show_status(self, msg: str, is_error: bool = False):
        self._hide_loading()
        self.status_label.setText(msg)
        self.status_label.setStyleSheet(
            "color: #e74c3c; font-size: 13px;" if is_error else f"color: {normal_text_color()}; font-size: 13px;"
        )
        self.status_label.show()

    def _show_error(self, msg: str):
        self._show_status(msg, is_error=True)
        if self.window():
            InfoBar.error(
                title="请求失败", content=msg,
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=5000,
                parent=self.window(),
            )

    def _on_safe_reset(self):
        """Reset page-specific state before worker cleanup."""
        self._loading = False
        self._load_cancelled = True
        self._progress_timer.stop()
        self.progress_ring.setValue(0)
        self.load_more_ring.setValue(0)

    def reset_to_idle(self):
        """Reset page to idle state after an error."""
        self._safe_reset()
        self._hide_loading()
        self.load_more_ring.setVisible(False)
        self.load_more_btn.setVisible(True)
        self.load_more_btn.setEnabled(True)
        self.load_more_btn.setText("加载更多")
        self.load_btn.setEnabled(True)
        self.url_input.setEnabled(True)

    # ── Load UP ──

    def load_url(self, url: str):
        """Load a UP主 space URL programmatically (from clipboard monitor)."""
        uid = extract_uid(url)
        if not uid:
            return False
        self.url_input.setText(url)
        self._on_load_up()
        return True

    def _on_load_up(self):
        url = self.url_input.text().strip()
        if not url:
            self._show_error("请输入UP主空间链接")
            return
        uid = extract_uid(url)
        if not uid:
            self._show_error("无法解析UID，请检查链接格式")
            return

        if not self._platform:
            self._init_platform()

        # Cancel any in-flight workers
        self._safe_reset()

        self._current_uid = uid
        self._current_page = 1
        self._videos_data = []
        self._video_cards = []
        self._cover_loaders = []
        self._load_cancelled = False

        self._show_loading("正在获取UP主信息...")
        self.load_btn.setEnabled(False)
        self.url_input.setEnabled(False)
        # Hide info_card during loading
        self.info_card.setVisible(False)
        self.avatar_label.clear()

        # Clear existing cards safely
        self._clear_grid()

        # Fetch info
        w = UpInfoWorker(self._platform, uid)
        w.finished.connect(self._on_info_done, Qt.QueuedConnection)
        w.error.connect(self._on_info_error, Qt.QueuedConnection)
        self._track_worker(w)
        w.start()

    def _on_info_done(self, info: dict):
        if self._load_cancelled:
            return  # was cancelled
        self._show_up_info(info)
        self._loading = True
        self._expected_page = 1
        self.loading_text.setText("正在获取视频列表...")
        w = UpVideosWorker(self._platform, self._current_uid, 1)
        w.finished.connect(self._on_videos_done, Qt.QueuedConnection)
        w.error.connect(self._on_videos_error, Qt.QueuedConnection)
        self._track_worker(w)
        w.start()
        self._collect_finished_workers()

    def _on_info_error(self, msg: str):
        self._loading = False
        if self._load_cancelled:
            return
        self._hide_loading()
        self._show_error(f"获取UP主信息失败: {msg}")
        self.load_btn.setEnabled(True)
        self.url_input.setEnabled(True)
        self._collect_finished_workers()

    def _show_up_info(self, info: dict):
        self.up_name.setText(info.get("name", "未知"))
        self.up_sign.setText(info.get("sign", "") or "这个人很懒，什么都没写")

        stats = []
        vc = info.get("video_count", 0)
        stats.append(f"{vc} 视频")
        stats.append(f"{format_count(info.get('follower', 0))} 粉丝")
        stats.append(f"{format_count(info.get('following', 0))} 关注")
        stats.append(f"Lv.{info.get('level', 0)}")
        self.up_stats.setText(" · ".join(stats))

        face_url = info.get("face", "")
        if face_url:
            loader = CoverLoader(face_url, "avatar")
            loader.url_loaded.connect(self._on_avatar_loaded)
            loader.start()
            self._cover_loaders.append(loader)

        self.info_card.setVisible(True)

    def _on_avatar_loaded(self, key: str, data: bytes):
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            scaled = pixmap.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.avatar_label.setPixmap(scaled)

    # ── Videos ──

    def _on_videos_done(self, data: dict):
        if self._load_cancelled:
            return
        if not self._loading:
            return
        self._loading = False

        self._hide_loading()

        resp_page = data.get("page", 0)
        if resp_page and resp_page != self._expected_page:
            return
        if resp_page:
            self._current_page = resp_page

        videos = data.get("videos", [])
        self._total_videos = data.get("count", 0)
        has_more = data.get("has_more", False)

        if not self._current_uid:
            return

        self._videos_data.extend(videos)

        if videos:
            try:
                self._add_video_cards(videos)
            except Exception:
                pass

        self.content_stack.setCurrentIndex(2)

        if has_more:
            self.load_more_ring.setVisible(False)
            self.load_more_btn.setVisible(True)
            self.load_more_btn.setEnabled(True)
            self.load_more_btn.setText(
                f"加载更多（{len(self._videos_data)}/{self._total_videos}）"
            )
        else:
            self.load_more_container.setVisible(False)

        self._show_status(
            f"共 {self._total_videos} 个视频，已加载 {len(self._videos_data)}"
        )
        self.load_btn.setEnabled(True)
        self.url_input.setEnabled(True)
        self._collect_finished_workers()

    def _on_videos_error(self, msg: str):
        if self._load_cancelled:
            return
        self._loading = False
        self._hide_loading()
        self.load_more_ring.setVisible(False)
        self.load_more_btn.setVisible(True)
        self.load_more_btn.setEnabled(True)
        self.load_more_btn.setText("加载更多")
        self._show_error(f"获取视频列表失败: {msg}")
        self.load_btn.setEnabled(True)
        self.url_input.setEnabled(True)
        self._collect_finished_workers()

    def _add_video_cards(self, videos: list[dict]):
        """Add video cards to the grid (3 columns)."""
        col = 3
        start_idx = len(self._video_cards)
        self.setUpdatesEnabled(False)
        try:
            for i, v in enumerate(videos):
                card = VideoCard(v)
                card.parse_clicked.connect(self._on_parse_video)
                row = (start_idx + i) // col
                col_idx = (start_idx + i) % col
                self.grid_layout.addWidget(card, row, col_idx)
                self._video_cards.append(card)

                # Load cover image
                cover_url = v.get("cover", "")
                if cover_url:
                    loader = CoverLoader(cover_url, v.get("bvid", ""))
                    loader.url_loaded.connect(self._on_cover_loaded)
                    loader.start()
                    self._cover_loaders.append(loader)
        finally:
            self.setUpdatesEnabled(True)

    def _on_cover_loaded(self, bvid: str, data: bytes):
        """Set cover image on the matching video card."""
        for card in self._video_cards:
            if card._bvid == bvid:
                card.set_cover(data)
                break

    def _on_load_more(self):
        if self._loading:
            return
        self._loading = True
        next_page = self._current_page + 1
        self._expected_page = next_page
        self.load_more_btn.setVisible(False)
        self.load_more_ring.setVisible(True)
        self._progress_value = 0
        self._progress_timer.start()
        # Keep strong reference via tracking list
        w = UpVideosWorker(self._platform, self._current_uid, next_page)
        w.finished.connect(self._on_videos_done, Qt.QueuedConnection)
        w.error.connect(self._on_videos_error, Qt.QueuedConnection)
        self._track_worker(w)
        w.start()

    def _on_parse_video(self, bvid: str):
        """Emit parse signal with the full video URL."""
        url = f"https://www.bilibili.com/video/{bvid}"
        self.parse_video.emit(url)

    def _clear_grid(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._video_cards.clear()
        self._cancel_cover_loaders()

    def clear(self):
        """Reset the page state."""
        self._safe_reset()
        self._current_uid = None
        self._current_page = 1
        self._expected_page = 1
        self._videos_data = []
        self._video_cards = []
        self._loading = False
        self._hide_loading()
        self.content_stack.setCurrentIndex(0)
        self.info_card.setVisible(False)
        self.avatar_label.clear()
        self._clear_grid()
        self.status_label.hide()
