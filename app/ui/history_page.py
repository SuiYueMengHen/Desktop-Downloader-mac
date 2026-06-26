"""
Download history page - browse, search, delete history, open download folder.
"""
import os
from datetime import datetime
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFrame,
)

from qfluentwidgets import (
    SearchLineEdit, PushButton,
    CardWidget, CaptionLabel, StrongBodyLabel,
    InfoBar, InfoBarPosition, FluentIcon as FIF,
    TitleLabel, HorizontalSeparator, SmoothScrollArea,
)

from app.history_manager import HistoryManager
from app.utils.helpers import format_size, format_duration, muted_text_color, secondary_text_color, configure_smooth_scroll, open_download_folder


class HistoryCard(CardWidget):
    """A single history entry card."""

    delete_clicked = Signal(str)
    open_folder_clicked = Signal(str)

    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self._entry = entry
        self._task_id = entry.get("task_id", "")

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # Title row
        title_layout = QHBoxLayout()
        self.title_label = StrongBodyLabel(
            entry.get("title", "未知标题")[:60]
        )
        self.title_label.setStyleSheet("font-size: 14px;")
        self.title_label.setWordWrap(True)

        # Page badge for multi-P
        page_label = entry.get("page_label", "")
        if page_label:
            badge = CaptionLabel(page_label)
            badge.setStyleSheet(
                "background-color: transparent; color: inherit; "
                "padding: 2px 8px; border-radius: 10px; font-size: 11px;"
            )
            title_layout.addWidget(badge, 0, Qt.AlignTop)

        title_layout.addWidget(self.title_label, 1)
        layout.addLayout(title_layout)

        # Meta row
        meta_parts = []
        platform = entry.get("platform", "")
        if platform:
            meta_parts.append(platform.upper())
        quality = entry.get("quality", "")
        if quality:
            meta_parts.append(quality)
        duration = entry.get("duration", 0)
        if duration:
            meta_parts.append(format_duration(duration))
        file_size = entry.get("file_size", 0)
        if file_size:
            meta_parts.append(format_size(file_size))
        timestamp = entry.get("timestamp", 0)
        if timestamp:
            dt = datetime.fromtimestamp(timestamp)
            meta_parts.append(dt.strftime("%Y-%m-%d %H:%M"))

        self.meta_label = CaptionLabel(" · ".join(meta_parts))
        self.meta_label.setStyleSheet(f"color: {secondary_text_color()}; font-size: 12px;")
        layout.addWidget(self.meta_label)

        # Action buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.open_btn = PushButton(FIF.FOLDER, "打开文件夹")
        self.open_btn.setFixedWidth(110)
        self.open_btn.clicked.connect(
            lambda: self.open_folder_clicked.emit(self._task_id)
        )
        btn_layout.addWidget(self.open_btn)

        self.delete_btn = PushButton(FIF.DELETE, "删除")
        self.delete_btn.setFixedWidth(80)
        self.delete_btn.clicked.connect(
            lambda: self.delete_clicked.emit(self._task_id)
        )
        btn_layout.addWidget(self.delete_btn)

        layout.addLayout(btn_layout)


class HistoryPage(SmoothScrollArea):
    """Download history page with search and management."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._history_manager = HistoryManager()
        self._current_query = ""
        
        # Debounce timer for refresh operations
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(500)  # 500ms debounce
        self._refresh_timer.timeout.connect(self._do_refresh)
        self._pending_refresh = False

        self._setup_ui()
        configure_smooth_scroll(self)
        self._load_history()

    def _setup_ui(self) -> None:
        self.container = QFrame(self)
        self.container.setObjectName("historyContainer")
        self.setWidget(self.container)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        self.vBoxLayout = QVBoxLayout(self.container)
        self.vBoxLayout.setContentsMargins(40, 20, 40, 20)
        self.vBoxLayout.setSpacing(16)

        # Header
        header_layout = QHBoxLayout()
        header = TitleLabel("下载历史")
        header.setStyleSheet("font-size: 28px; font-weight: 600;")
        header_layout.addWidget(header)
        header_layout.addStretch()

        self.clear_all_btn = PushButton(FIF.DELETE, "清空历史")
        self.clear_all_btn.clicked.connect(self._on_clear_all)
        header_layout.addWidget(self.clear_all_btn)
        self.vBoxLayout.addLayout(header_layout)

        desc = CaptionLabel("查看和管理已完成的下载记录")
        desc.setStyleSheet(f"font-size: 14px; color: {muted_text_color()};")
        self.vBoxLayout.addWidget(desc)

        # Search bar
        search_layout = QHBoxLayout()
        self.search_input = SearchLineEdit()
        self.search_input.setPlaceholderText("搜索历史记录（视频标题或ID）...")
        self.search_input.setMinimumHeight(36)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.searchSignal.connect(self._on_search)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        search_layout.addWidget(self.search_input, 1)
        self.vBoxLayout.addLayout(search_layout)

        self.vBoxLayout.addWidget(HorizontalSeparator())

        # Cards container
        self.cards_layout = QVBoxLayout()
        self.cards_layout.setSpacing(10)
        self.vBoxLayout.addLayout(self.cards_layout)

        # Empty state
        self.empty_label = CaptionLabel("暂无下载历史")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"color: {secondary_text_color()}; font-size: 14px; padding: 40px;")
        self.empty_label.hide()
        self.vBoxLayout.addWidget(self.empty_label)

        self.vBoxLayout.addStretch()

    def refresh(self) -> None:
        """Reload history from disk and refresh the UI with debouncing.
        
        Multiple rapid calls (e.g., from batch downloads) are coalesced
        into a single refresh after 500ms of inactivity.
        """
        self._pending_refresh = True
        self._refresh_timer.start()

    def _do_refresh(self) -> None:
        """Actually reload history from disk and refresh the UI."""
        self._pending_refresh = False
        self._history_manager.load()
        self._load_history()

    def _load_history(self) -> None:
        """Load and display history entries."""
        # Clear existing cards: takeAt removes from layout, then deleteLater
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        if self._current_query:
            entries = self._history_manager.search(self._current_query)
        else:
            entries = self._history_manager.get_all()

        if not entries:
            self.empty_label.show()
            return

        self.empty_label.hide()

        # Group by video_id for multi-P
        grouped = {}
        single = []
        for e in entries:
            vid = e.get("video_id", "")
            page_label = e.get("page_label", "")
            if vid and page_label:
                grouped.setdefault(vid, []).append(e)
            else:
                single.append(e)

        # Batch-create cards with updates disabled for smoother rendering
        self.setUpdatesEnabled(False)
        try:
            # Show grouped multi-P entries under a single card
            for vid, group in grouped.items():
                first = group[0]
                # Create a single card for the group
                card = CardWidget()
                card.setBorderRadius(8)
                card_layout = QVBoxLayout(card)
                card_layout.setSpacing(8)
                card_layout.setContentsMargins(16, 12, 16, 12)

                title_row = QHBoxLayout()
                title_label = StrongBodyLabel(first.get("title", "未知标题")[:60])
                title_label.setToolTip(first.get("title", ""))
                title_label.setStyleSheet("font-size: 14px;")
                title_label.setWordWrap(True)

                count_badge = CaptionLabel(f"{len(group)} 集")
                count_badge.setStyleSheet(
                    "background-color: transparent; color: inherit; "
                    "padding: 2px 10px; border-radius: 10px; font-size: 11px;"
                )

                title_row.addWidget(title_label, 1)
                title_row.addWidget(count_badge, 0, Qt.AlignTop)
                card_layout.addLayout(title_row)

                meta_parts = []
                platform = first.get("platform", "")
                if platform:
                    meta_parts.append(platform.upper())
                quality = first.get("quality", "")
                if quality:
                    meta_parts.append(quality)
                file_size = first.get("file_size", 0)
                if file_size:
                    meta_parts.append(format_size(file_size))
                timestamp = first.get("timestamp", 0)
                if timestamp:
                    dt = datetime.fromtimestamp(timestamp)
                    meta_parts.append(dt.strftime("%Y-%m-%d"))
                meta_label = CaptionLabel(" · ".join(meta_parts))
                meta_label.setStyleSheet(f"color: {secondary_text_color()}; font-size: 12px;")
                card_layout.addWidget(meta_label)

                card_layout.addWidget(HorizontalSeparator())

                for i, e in enumerate(group):
                    ep_row = QHBoxLayout()
                    ep_row.setSpacing(8)

                    pl = e.get("page_label", "")
                    ep_title = e.get("title", "")[:40]
                    dur = format_duration(e.get("duration", 0)) if e.get("duration") else ""

                    ep_label = CaptionLabel(f"{pl}  {ep_title}")
                    ep_label.setStyleSheet(f"color: {muted_text_color()}; font-size: 12px;")
                    ep_label.setToolTip(e.get("title", ""))
                    ep_label.setMinimumWidth(120)

                    if dur:
                        dur_label = CaptionLabel(dur)
                        dur_label.setStyleSheet(f"color: {muted_text_color()}; font-size: 11px;")
                        ep_row.addWidget(dur_label)

                    ep_row.addWidget(ep_label, 1)
                    ep_row.addStretch()

                    open_btn = PushButton(FIF.FOLDER, "")
                    open_btn.setToolTip("打开文件夹")
                    open_btn.setFixedSize(32, 32)
                    fp = e.get("file_path", "")
                    if fp and os.path.exists(fp):
                        open_btn.clicked.connect(
                            lambda checked=False, path=fp: open_download_folder(path)
                        )
                    else:
                        open_btn.setEnabled(False)
                    ep_row.addWidget(open_btn)

                    del_btn = PushButton(FIF.DELETE, "")
                    del_btn.setToolTip("删除记录")
                    del_btn.setFixedSize(32, 32)
                    tid = e.get("task_id", "")
                    del_btn.clicked.connect(
                        lambda checked=False, x=tid: self._delete_entry(x)
                    )
                    ep_row.addWidget(del_btn)

                    card_layout.addLayout(ep_row)
                    if i < len(group) - 1:
                        card_layout.addSpacing(2)

                self.cards_layout.addWidget(card)

            # Show single entries
            for e in single:
                card = self._create_history_card(e)
                self.cards_layout.addWidget(card)
        finally:
            self.setUpdatesEnabled(True)

    def _create_history_card(self, entry: dict) -> HistoryCard:
        """Create a HistoryCard widget from a history entry dict.

        Connects signal handlers for open-folder and delete actions.
        """
        card = HistoryCard(entry)
        card.open_folder_clicked.connect(self._on_open_folder)
        card.delete_clicked.connect(self._delete_entry)
        return card

    def append_entry(self) -> None:
        """Append a single history entry card (incremental update).

        Called when a download completes. Instead of a full rebuild,
        loads the latest entry from disk and inserts one card at the top.
        Falls back to full refresh if no cards are currently displayed.
        """
        if not self.cards_layout or self.cards_layout.count() == 0:
            self._do_refresh()
            return
        self._history_manager.load()
        entries = self._history_manager.get_all()
        if not entries:
            return
        entry = entries[0]
        card = self._create_history_card(entry)
        self.cards_layout.insertWidget(0, card)
        self.empty_label.hide()

    def _on_search(self) -> None:
        query = self.search_input.text().strip()
        self._current_query = query
        self._load_history()

    def _on_search_text_changed(self, text: str) -> None:
        if not text:
            self._current_query = ""
            self._load_history()

    def _on_open_folder(self, task_id: str) -> None:
        entries = self._history_manager.get_all()
        for e in entries:
            if e.get("task_id") == task_id:
                fp = e.get("file_path", "")
                if fp:
                    open_download_folder(fp)
                    return
        InfoBar.warning(
            title="未找到文件", content="该历史记录的文件路径不存在",
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP_RIGHT, duration=3000,
            parent=self.window(),
        )

    def _delete_entry(self, task_id: str) -> None:
        self._history_manager.delete(task_id)
        self._load_history()

    def _on_clear_all(self) -> None:
        from qfluentwidgets import MessageBox
        msg = MessageBox("清空历史", "确定要清空所有下载历史记录吗？\n此操作不可撤销。", self.window())
        msg.yesButton.setText("确定")
        msg.cancelButton.setText("取消")
        if msg.exec():
            self._history_manager.clear_all()
            self._load_history()
            InfoBar.success(
                title="已清空", content="所有下载历史已删除",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=2000,
                parent=self.window(),
            )
