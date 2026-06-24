"""
Collection/series page - browse and download videos from a Bilibili collection.
"""
from typing import Optional

from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFrame, QWidget,
    QStackedWidget, QCheckBox,
)

from qfluentwidgets import (
    SearchLineEdit, PushButton, PrimaryPushButton,
    CardWidget, CaptionLabel, BodyLabel, StrongBodyLabel,
    InfoBar, InfoBarPosition, FluentIcon as FIF,
    ImageLabel, TitleLabel, HorizontalSeparator, ProgressRing,
    SmoothScrollArea,
)

from app.utils.cover_loader import CoverLoader
from app.utils.async_worker import AsyncWorker
from app.utils.worker_mixin import WorkerMixin
from app.utils.helpers import format_duration, muted_text_color, secondary_text_color, normal_text_color, configure_smooth_scroll
from app.platforms.bilibili import BilibiliPlatform, extract_series_id


class SeriesInfoWorker(AsyncWorker):
    """Fetch collection/series metadata in background thread."""
    def __init__(self, platform: BilibiliPlatform, series_id: int):
        super().__init__()
        self.platform = platform
        self.series_id = series_id

    async def work(self):
        return await self.platform.get_series_info(self.series_id)


class SeriesVideosWorker(AsyncWorker):
    """Fetch paginated videos in a collection in background thread."""
    def __init__(self, platform: BilibiliPlatform, series_id: int, page: int = 1, page_size: int = 100):
        super().__init__()
        self.platform = platform
        self.series_id = series_id
        self.page = page
        self.page_size = page_size

    async def work(self):
        return await self.platform.get_series_videos(
            self.series_id, self.page, self.page_size
        )


def format_count(n: int) -> str:
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return str(n)


class VideoCheckCard(CardWidget):
    """A selectable video card with checkbox for collection items."""

    def __init__(self, video: dict, parent=None):
        super().__init__(parent)
        self._video = video
        self._bvid = video.get("bvid", "")
        self._title = video.get("title", "无标题")
        self._cover_data: Optional[bytes] = None

        layout = QHBoxLayout(self)
        layout.setSpacing(12)

        # Checkbox
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(True)
        layout.addWidget(self.checkbox)

        # Cover thumbnail
        self.cover_label = ImageLabel()
        self.cover_label.setFixedSize(120, 68)
        self.cover_label.setBorderRadius(4, 4, 4, 4)
        self.cover_label.setScaledContents(True)
        layout.addWidget(self.cover_label)

        # Info column
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        self.title_label = BodyLabel(self._title[:60])
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(f"font-size: 13px; color: {normal_text_color()};")
        info_layout.addWidget(self.title_label)

        duration = video.get("duration", 0)
        play = format_count(video.get("play", 0))
        meta = CaptionLabel(f"{play}次播放 · {format_duration(duration)}")
        meta.setStyleSheet(f"color: {muted_text_color()}; font-size: 11px;")
        info_layout.addWidget(meta)

        info_layout.addStretch()
        layout.addLayout(info_layout, 1)

        self.setBorderRadius(8)

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def set_checked(self, checked: bool):
        self.checkbox.setChecked(checked)

    def set_cover(self, data: bytes):
        self._cover_data = data
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            scaled = pixmap.scaled(120, 68, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.cover_label.setPixmap(scaled)


class CollectionPage(SmoothScrollArea, WorkerMixin):
    """Collection/series page - browse videos and send selected ones for parsing."""

    parse_batch_requested = Signal(list)  # list[str] of video URLs

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._platform: Optional[BilibiliPlatform] = None
        self._series_id: Optional[int] = None
        self._series_info: Optional[dict] = None
        self._current_page: int = 1
        self._expected_page: int = 1
        self._total_videos: int = 0
        self._videos_data: list[dict] = []
        self._video_cards: list[VideoCheckCard] = []
        self._loading = False
        self._load_cancelled = False
        self._progress_value = 0
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(33)
        self._progress_timer.timeout.connect(self._spin_progress)

        self._setup_ui()
        self._init_platform()
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
        self.container.setObjectName("collectionContainer")
        self.setWidget(self.container)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        self.vBoxLayout = QVBoxLayout(self.container)
        self.vBoxLayout.setContentsMargins(40, 20, 40, 20)
        self.vBoxLayout.setSpacing(16)

        # Header
        header = TitleLabel("UP主合集")
        header.setStyleSheet("font-size: 28px; font-weight: 600;")
        self.vBoxLayout.addWidget(header)

        desc = CaptionLabel("粘贴UP主合集链接，查看合集视频列表并选择下载")
        desc.setStyleSheet(f"font-size: 14px; color: {muted_text_color()};")
        self.vBoxLayout.addWidget(desc)

        # URL Input
        url_card = CardWidget(self.container)
        url_layout = QHBoxLayout(url_card)
        self.url_input = SearchLineEdit()
        self.url_input.setPlaceholderText("粘贴合集链接，如 https://space.bilibili.com/3493139067177129/lists/4908693")
        self.url_input.setMinimumHeight(40)
        self.url_input.setClearButtonEnabled(True)
        self.url_input.searchSignal.connect(self._on_load_collection)

        self.load_btn = PrimaryPushButton(FIF.SEARCH, "查看")
        self.load_btn.setMinimumHeight(40)
        self.load_btn.clicked.connect(self._on_load_collection)

        url_layout.addWidget(self.url_input, 1)
        url_layout.addWidget(self.load_btn)
        self.vBoxLayout.addWidget(url_card)

        # Status
        self.status_label = CaptionLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.hide()
        self.vBoxLayout.addWidget(self.status_label)

        # ── Collection Info Card ──
        self.info_card = CardWidget(self.container)
        self.info_card.setVisible(False)
        info_layout = QHBoxLayout(self.info_card)

        self.cover_label = ImageLabel()
        self.cover_label.setFixedSize(160, 90)
        self.cover_label.setBorderRadius(6, 6, 6, 6)
        self.cover_label.setScaledContents(True)

        info_text = QVBoxLayout()
        self.collection_name = StrongBodyLabel("")
        self.collection_name.setStyleSheet("font-size: 16px;")
        self.collection_name.setWordWrap(True)
        self.collection_meta = CaptionLabel("")
        self.collection_meta.setStyleSheet(f"color: {secondary_text_color()}; font-size: 12px;")
        self.collection_intro = CaptionLabel("")
        self.collection_intro.setStyleSheet(f"color: {muted_text_color()}; font-size: 12px;")
        self.collection_intro.setWordWrap(True)
        self.collection_intro.setMaximumHeight(60)

        info_text.addWidget(self.collection_name)
        info_text.addWidget(self.collection_meta)
        info_text.addWidget(self.collection_intro)
        info_text.addStretch()

        info_layout.addWidget(self.cover_label)
        info_layout.addLayout(info_text, 1)
        self.vBoxLayout.addWidget(self.info_card)

        self.vBoxLayout.addWidget(HorizontalSeparator())

        # ── Content Stack (empty / loading / content) ──
        self.content_stack = QStackedWidget()

        # Page 0: Empty
        self.empty_page = QWidget()
        ep_layout = QVBoxLayout(self.empty_page)
        ep_layout.setAlignment(Qt.AlignCenter)
        self.empty_hint = CaptionLabel("在上方输入合集链接后点击「查看」")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setStyleSheet(f"color: {secondary_text_color()}; font-size: 14px;")
        ep_layout.addWidget(self.empty_hint)
        self.content_stack.addWidget(self.empty_page)

        # Page 1: Loading
        self.loading_page = QWidget()
        lp_layout = QVBoxLayout(self.loading_page)
        lp_layout.setAlignment(Qt.AlignCenter)
        lp_layout.setContentsMargins(0, 40, 0, 40)
        self.progress_ring = ProgressRing()
        self.progress_ring.setFixedSize(60, 60)
        self.progress_ring.setStrokeWidth(6)
        self.loading_text = CaptionLabel("正在获取合集信息...")
        self.loading_text.setAlignment(Qt.AlignCenter)
        self.loading_text.setStyleSheet(f"color: {muted_text_color()}; font-size: 14px;")
        lp_layout.addWidget(self.progress_ring, 0, Qt.AlignCenter)
        lp_layout.addSpacing(12)
        lp_layout.addWidget(self.loading_text, 0, Qt.AlignCenter)
        self.content_stack.addWidget(self.loading_page)

        # Page 2: Content (video list + controls)
        self.content_page = QWidget()
        cp_layout = QVBoxLayout(self.content_page)
        cp_layout.setContentsMargins(0, 0, 0, 0)
        cp_layout.setSpacing(12)

        # Select all / count bar
        select_bar = QHBoxLayout()
        self.select_all_cb = QCheckBox("全选")
        self.select_all_cb.setChecked(True)
        self.select_all_cb.stateChanged.connect(self._on_select_all_changed)
        self.video_count_label = CaptionLabel("共 0 个视频")
        self.video_count_label.setStyleSheet(f"color: {muted_text_color()}; font-size: 12px;")

        select_bar.addWidget(self.select_all_cb)
        select_bar.addWidget(self.video_count_label)
        select_bar.addStretch()
        cp_layout.addLayout(select_bar)

        # Video cards scroll area
        self.cards_scroll = SmoothScrollArea()
        configure_smooth_scroll(self.cards_scroll)
        self.cards_scroll.setWidgetResizable(True)
        self.cards_scroll.setMinimumHeight(300)
        self.cards_scroll.enableTransparentBackground()

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setSpacing(6)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_scroll.setWidget(self.cards_container)
        cp_layout.addWidget(self.cards_scroll, 1)

        # Load more button
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

        # Download button
        self.download_btn = PrimaryPushButton(FIF.DOWNLOAD, "下载全部")
        self.download_btn.setMinimumHeight(44)
        self.download_btn.clicked.connect(self._on_download_selected)
        cp_layout.addWidget(self.download_btn)

        self.content_stack.addWidget(self.content_page)

        self.content_stack.setCurrentIndex(0)
        self.vBoxLayout.addWidget(self.content_stack, 1)
        self.vBoxLayout.addStretch()

    def _spin_progress(self):
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

    def load_url(self, url: str) -> bool:
        """Load a collection URL programmatically (from clipboard monitor)."""
        series_id = extract_series_id(url)
        if not series_id:
            return False
        self.url_input.setText(url)
        self._on_load_collection()
        return True

    def _on_load_collection(self):
        url = self.url_input.text().strip()
        if not url:
            self._show_error("请输入合集链接")
            return

        series_id = extract_series_id(url)
        if not series_id:
            self._show_error("无法解析合集ID，请检查链接格式")
            return

        if not self._platform:
            self._init_platform()

        self._safe_reset()

        self._series_id = series_id
        self._current_page = 1
        self._expected_page = 1
        self._videos_data = []
        self._video_cards = []
        self._cover_loaders = []
        self._load_cancelled = False

        self._show_loading("正在获取合集信息...")
        self.load_btn.setEnabled(False)
        self.url_input.setEnabled(False)
        self.info_card.setVisible(False)
        self.cover_label.clear()

        self._clear_cards()

        w = SeriesInfoWorker(self._platform, series_id)
        w.finished.connect(self._on_info_done, Qt.QueuedConnection)
        w.error.connect(self._on_info_error, Qt.QueuedConnection)
        self._track_worker(w)
        w.start()

    def _on_info_done(self, info: dict):
        if self._load_cancelled:
            return
        self._series_info = info
        self._show_collection_info(info)

        self._loading = True
        self.loading_text.setText("正在获取视频列表...")
        w = SeriesVideosWorker(self._platform, self._series_id, 1)
        w.finished.connect(self._on_videos_done, Qt.QueuedConnection)
        w.error.connect(self._on_videos_error, Qt.QueuedConnection)
        self._track_worker(w)
        w.start()

    def _on_info_error(self, msg: str):
        self._loading = False
        if self._load_cancelled:
            return
        self._hide_loading()
        self._show_error(f"获取合集信息失败: {msg}")
        self.load_btn.setEnabled(True)
        self.url_input.setEnabled(True)
        self._collect_finished_workers()

    def _show_collection_info(self, info: dict):
        self.collection_name.setText(info.get("name", "未命名合集"))

        upper = info.get("upper_name", "")
        count = info.get("media_count", 0)
        play = format_count(info.get("play", 0))
        self.collection_meta.setText(f"{upper} · {count} 个视频 · {play} 次播放")

        intro = info.get("intro", "")
        if intro:
            self.collection_intro.setText(intro[:150])
            self.collection_intro.setVisible(True)
        else:
            self.collection_intro.setVisible(False)

        cover_url = info.get("cover", "")
        if cover_url:
            loader = CoverLoader(cover_url, "cover")
            loader.url_loaded.connect(self._on_cover_loaded)
            loader.start()
            self._cover_loaders.append(loader)

        self.info_card.setVisible(True)

    def _on_cover_loaded(self, key: str, data: bytes):
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            scaled = pixmap.scaled(160, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.cover_label.setPixmap(scaled)

    def _on_videos_done(self, data: dict):
        if self._load_cancelled:
            return
        self._loading = False
        self._hide_loading()

        resp_page = data.get("page", 1)
        if resp_page and resp_page != self._expected_page and self._videos_data:
            return
        if resp_page:
            self._current_page = resp_page

        videos = data.get("videos", [])
        self._total_videos = data.get("count", 0)
        has_more = data.get("has_more", False)

        if not videos and not self._videos_data:
            self._show_error("该合集暂无视频")
            self.load_btn.setEnabled(True)
            self.url_input.setEnabled(True)
            self._collect_finished_workers()
            return

        self._videos_data.extend(videos)
        if videos:
            try:
                self._add_video_cards(videos)
            except Exception:
                pass

        # Update select all and count
        self.video_count_label.setText(f"共 {self._total_videos} 个视频，已加载 {len(self._videos_data)}")
        self._update_download_btn_text()

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
        self.setUpdatesEnabled(False)
        try:
            for v in videos:
                card = VideoCheckCard(v)
                card.checkbox.stateChanged.connect(self._update_download_btn_text)
                self.cards_layout.addWidget(card)
                self._video_cards.append(card)

                cover_url = v.get("cover", "")
                if cover_url:
                    loader = CoverLoader(cover_url, v.get("bvid", ""))
                    loader.url_loaded.connect(self._on_card_cover_loaded)
                    loader.start()
                    self._cover_loaders.append(loader)
        finally:
            self.setUpdatesEnabled(True)

    def _on_card_cover_loaded(self, bvid: str, data: bytes):
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
        w = SeriesVideosWorker(self._platform, self._series_id, next_page)
        w.finished.connect(self._on_videos_done, Qt.QueuedConnection)
        w.error.connect(self._on_videos_error, Qt.QueuedConnection)
        self._track_worker(w)
        w.start()

    def _on_select_all_changed(self):
        checked = self.select_all_cb.isChecked()
        for card in self._video_cards:
            card.set_checked(checked)
        self._update_download_btn_text()

    def _update_download_btn_text(self):
        selected = sum(1 for c in self._video_cards if c.is_checked())
        if selected > 0:
            self.download_btn.setText(f"下载选中（{selected} 个视频）")
        else:
            self.download_btn.setText("请选择要下载的视频")
        self.download_btn.setEnabled(selected > 0)

    def _on_download_selected(self):
        selected = [c for c in self._video_cards if c.is_checked()]
        if not selected:
            return

        urls = [
            f"https://www.bilibili.com/video/{card._bvid}"
            for card in selected
        ]
        self.parse_batch_requested.emit(urls)

    def _clear_cards(self):
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._video_cards.clear()
        self._cancel_cover_loaders()

    def clear(self):
        self._safe_reset()
        self._series_id = None
        self._series_info = None
        self._current_page = 1
        self._expected_page = 1
        self._videos_data = []
        self._video_cards = []
        self._loading = False
        self._hide_loading()
        self.content_stack.setCurrentIndex(0)
        self.info_card.setVisible(False)
        self.cover_label.clear()
        self._clear_cards()
        self.status_label.hide()
