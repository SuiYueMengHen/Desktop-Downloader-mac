"""
Search page - search Bilibili videos and uploaders by keyword.
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
    Pivot, SegmentedWidget, SmoothScrollArea,
)

from app.utils.cover_loader import CoverLoader
from app.utils.async_worker import AsyncWorker
from app.utils.worker_mixin import WorkerMixin
from app.utils.helpers import format_duration, muted_text_color, secondary_text_color, normal_text_color, configure_smooth_scroll
from app.platforms.bilibili import BilibiliPlatform


PAGE_SIZE = 20


class SearchVideosWorker(AsyncWorker):
    """Fetch video search results in background thread."""
    def __init__(self, platform: BilibiliPlatform, keyword: str, page: int = 1, page_size: int = PAGE_SIZE):
        super().__init__()
        self.platform = platform
        self.keyword = keyword
        self.page = page
        self.page_size = page_size

    async def work(self):
        return await self.platform.search_videos(self.keyword, self.page, self.page_size)


class SearchUploadersWorker(AsyncWorker):
    """Fetch uploader search results in background thread."""
    def __init__(self, platform: BilibiliPlatform, keyword: str, page: int = 1, page_size: int = PAGE_SIZE):
        super().__init__()
        self.platform = platform
        self.keyword = keyword
        self.page = page
        self.page_size = page_size

    async def work(self):
        return await self.platform.search_uploaders(self.keyword, self.page, self.page_size)


def format_count(n: int) -> str:
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return str(n)


class SearchVideoCard(CardWidget):
    """A single video card in search results."""

    parse_clicked = Signal(str)

    def __init__(self, video: dict, parent=None):
        super().__init__(parent)
        self._video = video
        self._bvid = video.get("bvid", "")
        self._cover_data = None
        self.setFixedWidth(280)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        self.cover_label = ImageLabel()
        self.cover_label.setFixedSize(260, 146)
        self.cover_label.setBorderRadius(6, 6, 6, 6)
        self.cover_label.setScaledContents(True)
        layout.addWidget(self.cover_label)

        title = video.get("title", "无标题")
        self.title_label = BodyLabel(title[:50])
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(f"font-size: 13px; color: {normal_text_color()};")
        layout.addWidget(self.title_label)

        author = video.get("author", "")
        duration = video.get("duration", 0)
        play = format_count(video.get("play", 0))
        meta = CaptionLabel(f"{author} · {play}次播放 · {format_duration(duration)}")
        meta.setStyleSheet(f"color: {muted_text_color()}; font-size: 11px;")
        layout.addWidget(meta)

        self.parse_btn = PushButton(FIF.DOWNLOAD, "解析下载")
        self.parse_btn.setFixedHeight(32)
        self.parse_btn.clicked.connect(lambda: self.parse_clicked.emit(self._bvid))
        layout.addWidget(self.parse_btn)

    def set_cover(self, data: bytes):
        self._cover_data = data
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            scaled = pixmap.scaled(260, 146, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.cover_label.setPixmap(scaled)


class SearchUploaderCard(CardWidget):
    """A single uploader card in search results."""

    view_clicked = Signal(int)  # uid

    def __init__(self, uploader: dict, parent=None):
        super().__init__(parent)
        self._uploader = uploader
        self._uid = uploader.get("uid", 0)
        self.setFixedWidth(380)

        layout = QHBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 12, 16, 12)

        # Avatar
        self.avatar_label = ImageLabel()
        self.avatar_label.setFixedSize(64, 64)
        self.avatar_label.setBorderRadius(32, 32, 32, 32)
        self.avatar_label.setScaledContents(True)
        layout.addWidget(self.avatar_label)

        # Info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        name = uploader.get("name", "未知")
        self.name_label = StrongBodyLabel(name)
        self.name_label.setStyleSheet(f"font-size: 15px; color: {normal_text_color()};")
        info_layout.addWidget(self.name_label)

        sign = uploader.get("sign", "") or "这个人很懒，什么都没写"
        self.sign_label = CaptionLabel(sign[:60])
        self.sign_label.setStyleSheet(f"color: {muted_text_color()}; font-size: 12px;")
        info_layout.addWidget(self.sign_label)

        fans = format_count(uploader.get("fans", 0))
        videos = uploader.get("videos", 0)
        level = uploader.get("level", 0)
        stats = CaptionLabel(f"粉丝 {fans} · {videos} 视频 · Lv.{level}")
        stats.setStyleSheet(f"color: {secondary_text_color()}; font-size: 11px;")
        info_layout.addWidget(stats)

        info_layout.addStretch()
        layout.addLayout(info_layout, 1)

        # View button
        self.view_btn = PrimaryPushButton(FIF.PEOPLE, "查看主页")
        self.view_btn.setFixedHeight(36)
        self.view_btn.clicked.connect(lambda: self.view_clicked.emit(self._uid))
        layout.addWidget(self.view_btn)

    def set_avatar(self, data: bytes):
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            scaled = pixmap.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.avatar_label.setPixmap(scaled)


class SearchPage(SmoothScrollArea, WorkerMixin):
    """Search page with keyword input and video/uploader results grid."""

    parse_video = Signal(str)
    view_uploader = Signal(int)  # uid -> jump to up_page

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._platform = None
        self._search_mode = "video"  # "video" or "uploader"
        self._current_keyword = ""
        self._current_page = 1
        self._expected_page = 1
        self._total_results = 0
        self._results_data = []
        self._video_cards = []
        self._uploader_cards = []
        self._loading = False
        self._progress_value = 0
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(50)
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
        self.container.setObjectName("searchContainer")
        self.setWidget(self.container)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        self.vBoxLayout = QVBoxLayout(self.container)
        self.vBoxLayout.setContentsMargins(40, 20, 40, 20)
        self.vBoxLayout.setSpacing(16)

        # Header
        header = TitleLabel("搜索")
        header.setStyleSheet("font-size: 28px; font-weight: 600;")
        self.vBoxLayout.addWidget(header)

        desc = CaptionLabel("搜索 Bilibili 视频或UP主，点击「解析下载」或「查看主页」")
        desc.setStyleSheet(f"font-size: 14px; color: {muted_text_color()};")
        self.vBoxLayout.addWidget(desc)

        # Search Input
        search_card = CardWidget(self.container)
        search_layout = QHBoxLayout(search_card)
        self.search_input = SearchLineEdit()
        self.search_input.setPlaceholderText("输入关键词搜索B站视频或UP主...")
        self.search_input.setMinimumHeight(40)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.searchSignal.connect(self._on_search)

        self.search_btn = PrimaryPushButton(FIF.SEARCH, "搜索")
        self.search_btn.setMinimumHeight(40)
        self.search_btn.clicked.connect(self._on_search)

        search_layout.addWidget(self.search_input, 1)
        search_layout.addWidget(self.search_btn)
        self.vBoxLayout.addWidget(search_card)

        # Mode switch (video / uploader)
        mode_layout = QHBoxLayout()
        self.mode_pivot = SegmentedWidget(self.container)
        self.mode_pivot.addItem(routeKey="video", text="搜索视频", onClick=lambda: self._switch_mode("video"))
        self.mode_pivot.addItem(routeKey="uploader", text="搜索UP主", onClick=lambda: self._switch_mode("uploader"))
        self.mode_pivot.setCurrentItem("video")
        mode_layout.addWidget(self.mode_pivot)
        mode_layout.addStretch()
        self.vBoxLayout.addLayout(mode_layout)

        # Status
        self.status_label = CaptionLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.hide()
        self.vBoxLayout.addWidget(self.status_label)

        # Content stack (empty / loading / results)
        self.content_stack = QStackedWidget()

        # Page 0: Empty
        self.empty_page = QWidget()
        ep_layout = QVBoxLayout(self.empty_page)
        ep_layout.setAlignment(Qt.AlignCenter)
        self.empty_hint = CaptionLabel("输入关键词搜索Bilibili视频或UP主")
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

        self.loading_text = CaptionLabel("正在搜索...")
        self.loading_text.setAlignment(Qt.AlignCenter)
        self.loading_text.setStyleSheet(f"color: {muted_text_color()}; font-size: 14px;")

        lp_layout.addWidget(self.progress_ring, 0, Qt.AlignCenter)
        lp_layout.addSpacing(12)
        lp_layout.addWidget(self.loading_text, 0, Qt.AlignCenter)
        self.content_stack.addWidget(self.loading_page)

        # Page 2: Results grid + load more
        self.content_page = QWidget()
        cp_layout = QVBoxLayout(self.content_page)
        cp_layout.setContentsMargins(0, 0, 0, 0)
        cp_layout.setSpacing(16)

        self.grid_label = StrongBodyLabel("搜索结果")
        self.grid_label.setStyleSheet(f"font-size: 16px; color: {normal_text_color()};")
        cp_layout.addWidget(self.grid_label)

        self.grid_widget = QWidget()
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(12)
        cp_layout.addWidget(self.grid_widget)

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

    def _switch_mode(self, mode: str):
        if self._search_mode == mode:
            return
        self._search_mode = mode
        self._safe_reset()
        self._clear_grid()
        self._results_data = []
        self._video_cards = []
        self._uploader_cards = []
        self.content_stack.setCurrentIndex(0)

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
        window = self.window()
        if window:
            InfoBar.error(
                title="搜索失败", content=msg,
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=5000,
                parent=window,
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
        self.search_btn.setEnabled(True)
        self.search_input.setEnabled(True)

    def _on_search(self):
        keyword = self.search_input.text().strip()
        if not keyword:
            self._show_error("请输入搜索关键词")
            return

        if not self._platform:
            self._init_platform()

        self._safe_reset()

        self._current_keyword = keyword
        self._current_page = 1
        self._expected_page = 1
        self._results_data = []
        self._video_cards = []
        self._uploader_cards = []
        self._cover_loaders = []
        self._load_cancelled = False

        label = "正在搜索视频..." if self._search_mode == "video" else "正在搜索UP主..."
        self._show_loading(label)
        self.search_btn.setEnabled(False)
        self.search_input.setEnabled(False)
        self._clear_grid()

        if self._search_mode == "video":
            w = SearchVideosWorker(self._platform, keyword, 1)
        else:
            w = SearchUploadersWorker(self._platform, keyword, 1)
        w.finished.connect(self._on_results_done, Qt.QueuedConnection)
        w.error.connect(self._on_results_error, Qt.QueuedConnection)
        self._track_worker(w)
        w.start()

    def _on_results_done(self, data: dict):
        if self._load_cancelled:
            return

        self._hide_loading()

        resp_page = data.get("page", 0)
        if resp_page and resp_page != self._expected_page:
            return
        if resp_page:
            self._current_page = resp_page

        if self._search_mode == "video":
            items = data.get("videos", [])
            self._total_results = data.get("count", 0)
            self._results_data.extend(items)
            if items:
                self._add_video_cards(items)
        else:
            items = data.get("uploaders", [])
            self._total_results = data.get("count", 0)
            self._results_data.extend(items)
            if items:
                self._add_uploader_cards(items)

        has_more = data.get("has_more", False)
        self.content_stack.setCurrentIndex(2)

        if has_more:
            self.load_more_ring.setVisible(False)
            self.load_more_btn.setVisible(True)
            self.load_more_btn.setEnabled(True)
            self.load_more_btn.setText(
                f"加载更多（{len(self._results_data)}/{self._total_results}）"
            )
        else:
            self.load_more_container.setVisible(False)

        label = "视频" if self._search_mode == "video" else "UP主"
        self._show_status(
            f"共 {self._total_results} 个{label}，已加载 {len(self._results_data)}"
        )
        self.search_btn.setEnabled(True)
        self.search_input.setEnabled(True)
        self._collect_finished_workers()

    def _on_results_error(self, msg: str):
        if self._load_cancelled:
            return
        self._hide_loading()
        self.load_more_ring.setVisible(False)
        self.load_more_btn.setVisible(True)
        self.load_more_btn.setEnabled(True)
        self.load_more_btn.setText("加载更多")
        self._show_error(f"搜索失败: {msg}")
        self.search_btn.setEnabled(True)
        self.search_input.setEnabled(True)
        self._collect_finished_workers()

    def _add_video_cards(self, videos):
        col = 3
        start_idx = len(self._video_cards)
        self.setUpdatesEnabled(False)
        try:
            for i, v in enumerate(videos):
                card = SearchVideoCard(v)
                card.parse_clicked.connect(self._on_parse_video)
                row = (start_idx + i) // col
                col_idx = (start_idx + i) % col
                self.grid_layout.addWidget(card, row, col_idx)
                self._video_cards.append(card)

                cover_url = v.get("cover", "")
                if cover_url:
                    loader = CoverLoader(cover_url, v.get("bvid", ""))
                    loader.url_loaded.connect(self._on_cover_loaded)
                    loader.start()
                    self._cover_loaders.append(loader)
        finally:
            self.setUpdatesEnabled(True)

    def _add_uploader_cards(self, uploaders):
        col = 2
        start_idx = len(self._uploader_cards)
        self.setUpdatesEnabled(False)
        try:
            for i, u in enumerate(uploaders):
                card = SearchUploaderCard(u)
                card.view_clicked.connect(self._on_view_uploader)
                row = (start_idx + i) // col
                col_idx = (start_idx + i) % col
                self.grid_layout.addWidget(card, row, col_idx)
                self._uploader_cards.append(card)

                face_url = u.get("face", "")
                uid = u.get("uid", 0)
                if face_url:
                    loader = CoverLoader(face_url, str(uid))
                    loader.url_loaded.connect(self._on_avatar_loaded)
                    loader.start()
                    self._cover_loaders.append(loader)
        finally:
            self.setUpdatesEnabled(True)

    def _on_cover_loaded(self, bvid: str, data: bytes):
        for card in self._video_cards:
            if card._bvid == bvid:
                card.set_cover(data)
                break

    def _on_avatar_loaded(self, key: str, data: bytes):
        for card in self._uploader_cards:
            if str(card._uid) == key:
                card.set_avatar(data)
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

        if self._search_mode == "video":
            w = SearchVideosWorker(self._platform, self._current_keyword, next_page)
        else:
            w = SearchUploadersWorker(self._platform, self._current_keyword, next_page)
        w.finished.connect(self._on_results_done, Qt.QueuedConnection)
        w.error.connect(self._on_results_error, Qt.QueuedConnection)
        self._track_worker(w)
        w.start()

    def _on_parse_video(self, bvid: str):
        url = f"https://www.bilibili.com/video/{bvid}"
        self.parse_video.emit(url)

    def _on_view_uploader(self, uid: int):
        """Emit signal to jump to UP主 space page."""
        self.view_uploader.emit(uid)

    def _clear_grid(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._video_cards.clear()
        self._uploader_cards.clear()
        self._cancel_cover_loaders()

    def focus_search(self):
        """Focus the search input for keyboard shortcut."""
        self.search_input.setFocus()
        self.search_input.selectAll()
