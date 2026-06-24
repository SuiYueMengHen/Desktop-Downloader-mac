"""
Home/download page - URL input, video info display, quality selection.
Uses QThread for non-blocking yt-dlp parsing to keep UI responsive.
"""
from typing import Optional

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFrame, QWidget,
)

from qfluentwidgets import (
    SearchLineEdit, PushButton, ComboBox,
    PrimaryPushButton, CardWidget, CaptionLabel, BodyLabel,
    InfoBar, InfoBarPosition, FluentIcon as FIF,
    ImageLabel, TitleLabel, StrongBodyLabel, HorizontalSeparator,
    CheckBox, SmoothScrollArea,
)

from app.utils.cover_loader import CoverLoader
from app.utils.async_worker import AsyncWorker
from app.utils.worker_mixin import WorkerMixin
from app.utils.helpers import (
    detect_platform, format_duration,
    muted_text_color, secondary_text_color, normal_text_color,
    configure_smooth_scroll,
)
from app.platforms.base import (
    BasePlatform, VideoInfo, VideoQuality, DownloadTask,
)


QUALITY_LABELS = {
    VideoQuality.UNKNOWN: "自动",
    VideoQuality.Q_144P: "144p",
    VideoQuality.Q_240P: "240P 极速",
    VideoQuality.Q_360P: "360P 流畅",
    VideoQuality.Q_480P: "480P 标清",
    VideoQuality.Q_540P: "540p",
    VideoQuality.Q_720P: "720P 准高清",
    VideoQuality.Q_1080P: "1080P 高清",
    VideoQuality.Q_1080P_HIGH_BITRATE: "1080P 高码率",
    VideoQuality.Q_1440P: "1440p (2K)",
    VideoQuality.Q_2160P: "4K 超高清",
    VideoQuality.Q_4320P: "8K 超高清",
}


class ParseWorker(AsyncWorker):
    """Non-blocking async video info parser."""
    def __init__(self, platform: BasePlatform, url: str):
        super().__init__()
        self.platform = platform
        self.url = url

    async def work(self):
        return await self.platform.parse_url(self.url)


class DownloadResolveWorker(AsyncWorker):
    """Resolves streams for a video in background thread."""
    def __init__(self, platform: BasePlatform, video_info: VideoInfo,
                 quality: VideoQuality, page_index: int = 0,
                 page_label: str = ""):
        super().__init__()
        self.platform = platform
        self.video_info = video_info
        self.quality = quality
        self.page_index = page_index
        self.page_label = page_label

    async def work(self):
        return await self.platform.resolve_download(
            self.video_info, self.quality,
            page_index=self.page_index, page_label=self.page_label,
        )


class BatchResultCard(CardWidget):

    download_requested = Signal(object)
    card_finished = Signal(object)  # emitted when all downloads added, card can be removed

    def __init__(self, video_info: VideoInfo, platform: BasePlatform, parent=None):
        super().__init__(parent)
        self._video_info = video_info
        self._platform = platform
        self._workers: list[QThread] = []
        self._page_checkboxes: list[CheckBox] = []
        self._pending_page_resolves: int = 0

        self.setBorderRadius(8)
        layout = QHBoxLayout(self)
        layout.setSpacing(12)

        self.cover_label = ImageLabel()
        self.cover_label.setFixedSize(120, 68)
        self.cover_label.setBorderRadius(4, 4, 4, 4)
        self.cover_label.setScaledContents(True)
        layout.addWidget(self.cover_label)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        self.title_label = StrongBodyLabel(video_info.title[:60])
        self.title_label.setWordWrap(False)
        info_layout.addWidget(self.title_label)

        author = video_info.author_name or "未知作者"
        duration = format_duration(video_info.duration) if video_info.duration > 0 else "未知时长"
        platform_display = "Bilibili" if video_info.platform == "bilibili" else video_info.platform
        self.meta_label = CaptionLabel(f"{platform_display} · {author} · {duration} · {video_info.video_id}")
        self.meta_label.setStyleSheet(f"color: {muted_text_color()};")
        info_layout.addWidget(self.meta_label)

        self.page_separator = HorizontalSeparator()
        self.page_separator.setVisible(False)
        info_layout.addWidget(self.page_separator)

        self.page_selector_widget = QWidget()
        self.page_selector_widget.setVisible(False)
        page_selector_layout = QVBoxLayout(self.page_selector_widget)
        page_selector_layout.setContentsMargins(0, 0, 0, 0)
        self.page_scroll = SmoothScrollArea()
        configure_smooth_scroll(self.page_scroll)
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFixedHeight(100)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page_scroll_content = QWidget()
        self.page_checkboxes_layout = QVBoxLayout(page_scroll_content)
        self.page_scroll.setWidget(page_scroll_content)
        page_selector_layout.addWidget(self.page_scroll)
        info_layout.addWidget(self.page_selector_widget)

        controls_layout = QHBoxLayout()
        quality_label = BodyLabel("画质:")
        self.quality_combo = ComboBox()
        self.quality_combo.setMinimumWidth(160)
        controls_layout.addWidget(quality_label)
        controls_layout.addWidget(self.quality_combo)

        self.audio_only_cb = CheckBox("仅音频(MP3)")
        self.audio_only_cb.setToolTip("只下载音频并转换为MP3格式")
        controls_layout.addWidget(self.audio_only_cb)

        controls_layout.addStretch()

        self.download_btn = PrimaryPushButton(FIF.DOWNLOAD, "下载")
        self.download_btn.setFixedHeight(36)
        self.download_btn.clicked.connect(self._on_download_clicked)
        controls_layout.addWidget(self.download_btn)

        info_layout.addLayout(controls_layout)
        layout.addLayout(info_layout, 1)

        if video_info.available_qualities:
            for q in video_info.available_qualities:
                label = QUALITY_LABELS.get(q, q.value)
                self.quality_combo.addItem(label, userData=q)
            self.quality_combo.setCurrentIndex(len(video_info.available_qualities) - 1)
        else:
            self.quality_combo.addItem("自动", userData=VideoQuality.UNKNOWN)

        self._setup_page_selector(video_info)

        if video_info.cover_url:
            loader = CoverLoader(video_info.cover_url)
            loader.loaded.connect(self._on_cover_loaded)
            self._workers.append(loader)
            loader.start()

    def _setup_page_selector(self, video_info: VideoInfo):
        pages = video_info.raw_data.get("pages", [])
        total_pages = video_info.raw_data.get("total_pages", 0) or len(pages)
        is_multi = total_pages > 1 and len(pages) > 1
        if not is_multi:
            return
        self.page_separator.setVisible(True)
        self.page_selector_widget.setVisible(True)
        self._all_selected = True
        for p in pages:
            page_num = p.get("page", 0) + 1
            part_name = p.get("part", f"P{page_num:02d}")
            page_dur = format_duration(p.get("duration", 0))
            cb = CheckBox(f"P{page_num:02d} - {part_name}（{page_dur}）")
            cb.setChecked(True)
            cb.page_index = p.get("page", 0)
            cb.page_label = f"P{page_num:02d}"
            cb.stateChanged.connect(self._on_page_check_changed)
            self.page_checkboxes_layout.addWidget(cb)
            self._page_checkboxes.append(cb)
        self._update_page_download_btn_text()

    def _update_page_download_btn_text(self):
        if not self._page_checkboxes:
            self.download_btn.setText("下载")
            return
        checked = sum(1 for cb in self._page_checkboxes if cb.isChecked())
        total = len(self._page_checkboxes)
        if checked == total:
            self.download_btn.setText(f"下载（全部 {total} 集）")
        elif checked > 0:
            self.download_btn.setText(f"下载（已选 {checked} 集）")
        else:
            self.download_btn.setText("下载")

    def _on_page_check_changed(self):
        checked = sum(1 for cb in self._page_checkboxes if cb.isChecked())
        total = len(self._page_checkboxes)
        self._all_selected = (checked == total)
        self._update_page_download_btn_text()

    def _get_selected_pages(self) -> list[tuple[int, str]]:
        if not self._page_checkboxes:
            return [(0, "")]
        result = []
        for cb in self._page_checkboxes:
            if cb.isChecked():
                result.append((cb.page_index, cb.page_label))
        return result

    def cleanup(self):
        """Disconnect all worker signals. Does NOT clear _workers — caller
        must transfer running workers to a longer-lived list to prevent
        'QThread: Destroyed while thread is still running' crash."""
        for w in self._workers:
            for sig_name in ("loaded", "url_loaded", "finished", "error"):
                sig = getattr(w, sig_name, None)
                if sig is not None:
                    try:
                        sig.disconnect()
                    except (TypeError, RuntimeError):
                        pass

    def _on_cover_loaded(self, data: bytes):
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            scaled = pixmap.scaled(120, 68, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.cover_label.setPixmap(scaled)

    def _on_download_clicked(self):
        quality = self.quality_combo.currentData() or VideoQuality.UNKNOWN
        self.download_btn.setEnabled(False)
        self.download_btn.setText("获取地址...")

        pages = self._get_selected_pages()
        self._pending_page_resolves = len(pages)

        for page_idx, page_label in pages:
            worker = DownloadResolveWorker(
                self._platform, self._video_info, quality,
                page_index=page_idx, page_label=page_label,
            )
            worker.finished.connect(self._on_page_resolve_done)
            worker.error.connect(self._on_page_resolve_error)
            self._workers.append(worker)
            worker.start()

    def _on_page_resolve_done(self, task: DownloadTask):
        self._pending_page_resolves -= 1
        task.audio_only = self.audio_only_cb.isChecked()
        self.download_requested.emit(task)
        if self._pending_page_resolves <= 0:
            self.download_btn.setEnabled(True)
            self.download_btn.setText("✓ 已添加")
            self.card_finished.emit(self)

    def _on_page_resolve_error(self, msg: str):
        self._pending_page_resolves -= 1
        if self._pending_page_resolves <= 0:
            self.download_btn.setEnabled(True)
            self.download_btn.setText("下载")
        window = self.window()
        if window:
            InfoBar.error(
                title="获取下载地址失败", content=msg,
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=5000,
                parent=window,
            )


class HomePage(SmoothScrollArea, WorkerMixin):
    """Main download page with URL input, video info, and download controls."""

    download_requested = Signal(object)  # DownloadTask
    resolve_complete = Signal()  # all resolves for current download finished
    parse_complete = Signal()  # current URL parsed and info displayed
    batch_cancelled = Signal()  # user manually parsed URL during batch mode

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        WorkerMixin.__init_from__(self)
        configure_smooth_scroll(self)
        self._platforms = {}
        self._current_platform: Optional[BasePlatform] = None

        self._in_batch_mode: bool = False
        self._batch_cards: list[BatchResultCard] = []

        self._setup_ui()
        self._init_platforms()

    def _init_platforms(self):
        if self.main_window:
            self._platforms["bilibili"] = self.main_window.bilibili

    def _setup_ui(self):
        self.container = QFrame(self)
        self.container.setObjectName("homeContainer")
        self.setWidget(self.container)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        self.vBoxLayout = QVBoxLayout(self.container)
        self.vBoxLayout.setContentsMargins(40, 20, 40, 20)
        self.vBoxLayout.setSpacing(16)

        # ── Header ──
        header = TitleLabel("视频下载")
        header.setStyleSheet("font-size: 28px; font-weight: 600;")
        desc = CaptionLabel("支持 Bilibili 视频下载，粘贴视频链接开始解析")
        desc.setStyleSheet(f"font-size: 14px; color: {muted_text_color()};")

        self.vBoxLayout.addWidget(header)
        self.vBoxLayout.addWidget(desc)
        self.vBoxLayout.addSpacing(10)

        # ── URL Input Area ──
        self.url_card = CardWidget(self.container)
        url_card_layout = QVBoxLayout(self.url_card)

        url_input_layout = QHBoxLayout()
        self.url_input = SearchLineEdit(self.url_card)
        self.url_input.setPlaceholderText(
            "粘贴 Bilibili 视频链接，如 https://www.bilibili.com/video/BV1xx..."
        )
        self.url_input.setMinimumHeight(40)
        self.url_input.setClearButtonEnabled(True)
        self.url_input.searchSignal.connect(self._on_parse_url)

        self.parse_btn = PrimaryPushButton(FIF.SEARCH, "解析")
        self.parse_btn.setMinimumHeight(40)
        self.parse_btn.clicked.connect(self._on_parse_url)

        self.batch_btn = PushButton(FIF.ADD, "批量导入")
        self.batch_btn.setMinimumHeight(40)
        self.batch_btn.clicked.connect(self._on_batch_import)

        url_input_layout.addWidget(self.url_input, 1)
        url_input_layout.addWidget(self.parse_btn)
        url_input_layout.addWidget(self.batch_btn)
        url_card_layout.addLayout(url_input_layout)

        platform_label = CaptionLabel(
            "支持平台: Bilibili"
        )
        platform_label.setStyleSheet(f"color: {secondary_text_color()}; font-size: 12px;")
        url_card_layout.addWidget(platform_label)
        self.vBoxLayout.addWidget(self.url_card)

        # ── Loading / Status ──
        self.status_label = CaptionLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.hide()
        self.vBoxLayout.addWidget(self.status_label)

        # ── Results Area (unified for single and batch parse) ──
        self.results_header = StrongBodyLabel("解析结果")
        self.results_header.setStyleSheet("font-size: 16px;")
        self.results_header.setVisible(False)
        self.vBoxLayout.addWidget(self.results_header)

        self.results_scroll = SmoothScrollArea()
        configure_smooth_scroll(self.results_scroll)
        self.results_scroll.setWidgetResizable(True)
        self.results_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        results_scroll_content = QWidget()
        self.batch_results_layout = QVBoxLayout(results_scroll_content)
        self.batch_results_layout.setContentsMargins(0, 0, 0, 0)
        self.batch_results_layout.setSpacing(8)
        self.results_scroll.setWidget(results_scroll_content)
        self.vBoxLayout.addWidget(self.results_scroll, 1)

        self._empty_hint = CaptionLabel("暂无解析结果，请粘贴视频链接开始解析")
        self._empty_hint.setAlignment(Qt.AlignCenter)
        self._empty_hint.setStyleSheet(f"color: {secondary_text_color()}; font-size: 14px; padding: 40px;")
        self.vBoxLayout.addWidget(self._empty_hint)

    def _show_status(self, msg: str, is_error: bool = False):
        self.status_label.setText(msg)
        self.status_label.setStyleSheet(
            f"color: #e74c3c; font-size: 13px;" if is_error else f"color: {normal_text_color()}; font-size: 13px;"
        )
        self.status_label.show()

    def _show_error(self, msg: str):
        self._show_status(msg, is_error=True)
        if self.window():
            InfoBar.error(
                title="解析失败", content=msg,
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=5000,
                parent=self.window(),
            )

    # ── Safe Worker Lifecycle ──

    def _on_batch_import(self):
        """Open batch import dialog and start batch parsing."""
        from app.ui.batch_import_dialog import BatchImportDialog
        dialog = BatchImportDialog(self.window())
        if dialog.exec():
            urls = dialog.get_urls()
            if not urls:
                return
            self.enter_batch_mode()
            mw = self.main_window
            if mw and hasattr(mw, '_on_batch_urls'):
                mw._on_batch_urls(urls)
            else:
                self._show_status(f"准备批量解析 {len(urls)} 个链接...")
                self._batch_urls = list(urls)
                self._batch_index = 0
                self._submit_next_batch()

    def _submit_next_batch(self):
        """Submit next URL in the batch queue."""
        if not hasattr(self, '_batch_urls') or self._batch_index >= len(self._batch_urls):
            self._batch_urls = []
            self._batch_index = 0
            InfoBar.success(
                title="批量解析完成",
                content="所有视频已解析完毕",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=5000,
                parent=self.window(),
            )
            return
        url = self._batch_urls[self._batch_index]
        self._batch_index += 1
        self._on_parse_url_batch(url)

    # ── Parse URL ──

    def _on_parse_url(self):
        if self._in_batch_mode:
            self._exit_batch_mode()

        url = self.url_input.text().strip()
        if not url:
            self._show_error("请输入视频链接")
            return

        platform_name = detect_platform(url)
        if not platform_name:
            self._show_error("无法识别平台，目前仅支持: Bilibili")
            return
        if platform_name not in self._platforms:
            self._show_error(f"平台 {platform_name} 尚未实现")
            return

        self._show_status(f"正在解析 {platform_name} 视频信息...")
        self.parse_btn.setEnabled(False)
        self.url_input.setEnabled(False)
        self._safe_reset()
        self._clear_results()

        # Run parsing in background thread
        self._current_platform = self._platforms[platform_name]
        worker = ParseWorker(self._current_platform, url)
        worker.finished.connect(self._on_parse_done)
        worker.error.connect(self._on_parse_error)
        self._track_worker(worker)
        worker.start()

    def _on_parse_done(self, video_info: VideoInfo):
        card = BatchResultCard(video_info, self._current_platform, self)
        card.download_requested.connect(self._on_batch_card_download)
        card.card_finished.connect(self._on_card_finished)
        self._batch_cards.append(card)
        self.batch_results_layout.addWidget(card)
        self._show_results_area()
        self.parse_btn.setEnabled(True)
        self.url_input.setEnabled(True)
        self._collect_finished_workers()
        self.parse_complete.emit()

    def _on_parse_error(self, msg: str):
        self._show_error(f"解析失败: {msg}")
        self.parse_btn.setEnabled(True)
        self.url_input.setEnabled(True)
        self._collect_finished_workers()

    def _show_results_area(self):
        """Show the results area and hide the empty hint."""
        self.results_header.setVisible(True)
        self.results_scroll.setVisible(True)
        self._empty_hint.setVisible(False)

    def _clear_results(self):
        """Clear all result cards."""
        for card in self._batch_cards:
            card.cleanup()
            # Transfer workers to HomePage before card deletion, preventing
            # "QThread: Destroyed while thread is still running" crash when
            # Python GC collects QThread wrappers whose C++ threads still run.
            for w in card._workers:
                self._workers.append(w)
            card._workers.clear()
            self.batch_results_layout.removeWidget(card)
            card.deleteLater()
        self._batch_cards.clear()
        self.results_header.setVisible(False)
        self.results_scroll.setVisible(False)
        self._empty_hint.setVisible(True)

    def enter_batch_mode(self):
        self._in_batch_mode = True
        self._clear_results()

    def _exit_batch_mode(self):
        """Cancel batch mode and clear all results."""
        self._in_batch_mode = False
        self._clear_results()
        self.batch_cancelled.emit()

    def _finish_batch_mode(self):
        """Mark batch mode as finished without clearing results.

        Called when all batch URLs have been processed. Unlike
        _exit_batch_mode(), this preserves the results so the user
        can review and download them.
        """
        self._in_batch_mode = False

    def on_page_left(self):
        """Don't cancel workers during batch mode — let it continue in background."""
        if self._in_batch_mode:
            return
        self._safe_reset()

    def reset_to_idle(self):
        """Reset page to idle state after an error."""
        if self._in_batch_mode:
            self._exit_batch_mode()
        self._safe_reset()
        self.parse_btn.setEnabled(True)
        self.url_input.setEnabled(True)

    def _on_parse_url_batch(self, url: str):
        platform_name = detect_platform(url)
        if not platform_name or platform_name not in self._platforms:
            self._collect_finished_workers()
            self.parse_complete.emit()
            return
        self._current_platform = self._platforms[platform_name]
        worker = ParseWorker(self._current_platform, url)
        worker.finished.connect(self._on_batch_parse_done)
        worker.error.connect(self._on_batch_parse_error)
        self._track_worker(worker)
        worker.start()

    def _on_batch_parse_done(self, video_info: VideoInfo):
        if not self._in_batch_mode:
            self._collect_finished_workers()
            return
        card = BatchResultCard(video_info, self._current_platform, self)
        card.download_requested.connect(self._on_batch_card_download)
        card.card_finished.connect(self._on_card_finished)
        self._batch_cards.append(card)
        self.batch_results_layout.addWidget(card)
        self._show_results_area()
        self._collect_finished_workers()
        self.parse_complete.emit()

    def _on_batch_parse_error(self, msg: str):
        if not self._in_batch_mode:
            self._collect_finished_workers()
            return
        self._show_error(f"批量解析部分视频失败: {msg}")
        self._collect_finished_workers()
        self.parse_complete.emit()

    def _on_batch_card_download(self, task: DownloadTask):
        self.download_requested.emit(task)

    def _on_card_finished(self, card):
        """Remove a card after its downloads have been added to the download list."""
        if card not in self._batch_cards:
            return
        card.cleanup()
        for w in card._workers:
            self._workers.append(w)
        card._workers.clear()
        self.batch_results_layout.removeWidget(card)
        card.deleteLater()
        self._batch_cards.remove(card)
        if not self._batch_cards:
            self.results_header.setVisible(False)
            self.results_scroll.setVisible(False)
            self._empty_hint.setVisible(True)


