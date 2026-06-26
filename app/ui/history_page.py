"""
Download history page - browse, search, delete history, open download folder.
"""
import csv
import os
from datetime import datetime
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFrame, QWidget, QCheckBox,
)

from qfluentwidgets import (
    SearchLineEdit, PushButton, RoundMenu, Action,
    CardWidget, CaptionLabel, StrongBodyLabel,
    InfoBar, InfoBarPosition, FluentIcon as FIF,
    TitleLabel, HorizontalSeparator, SmoothScrollArea,
)

from app.history_manager import HistoryManager
from app.utils.helpers import format_size, format_duration, configure_smooth_scroll, open_download_folder
from app.theme import apply_style


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
        self.checkbox = QCheckBox()
        self.checkbox.setVisible(False)
        self.checkbox.setProperty("task_id", self._task_id)
        title_layout.addWidget(self.checkbox, 0, Qt.AlignLeft)

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
        apply_style(self.meta_label, "font-size: 12px;", "secondary")
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

    switch_to_home = Signal()

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
        self._batch_mode = False

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

        # Export button with dropdown menu
        self._export_btn = PushButton(FIF.DOWNLOAD, "导出")
        self._export_menu = RoundMenu(parent=self)
        self._export_menu.addAction(
            Action(FIF.DOWNLOAD, "导出 CSV...", triggered=self._export_csv)
        )
        self._export_menu.addAction(
            Action(FIF.SHARE, "导出 JSON...", triggered=self._export_json)
        )
        self._export_btn.setMenu(self._export_menu)
        header_layout.addWidget(self._export_btn)

        # Batch mode toggle
        self._batch_toggle_btn = PushButton("批量删除")
        self._batch_toggle_btn.clicked.connect(self._toggle_batch_mode)
        header_layout.addWidget(self._batch_toggle_btn)

        self.clear_all_btn = PushButton(FIF.DELETE, "清空历史")
        self.clear_all_btn.clicked.connect(self._on_clear_all)
        header_layout.addWidget(self.clear_all_btn)
        self.vBoxLayout.addLayout(header_layout)

        desc = CaptionLabel("查看和管理已完成的下载记录")
        apply_style(desc, "font-size: 14px;", "muted")
        self.vBoxLayout.addWidget(desc)

        # Stats bar
        self._stats_widget = QWidget()
        stats_layout = QHBoxLayout(self._stats_widget)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(24)
        self._stat_total = CaptionLabel("总计: --")
        self._stat_size = CaptionLabel("总大小: --")
        self._stat_platform = CaptionLabel("平台: --")
        self._stat_avg = CaptionLabel("平均: --")
        for label in (self._stat_total, self._stat_size, self._stat_platform, self._stat_avg):
            apply_style(label, "font-size: 12px;", "muted")
            stats_layout.addWidget(label)
        stats_layout.addStretch()
        self.vBoxLayout.addWidget(self._stats_widget)

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

        # Batch action bar (hidden by default)
        self._batch_bar = QFrame()
        batch_bar_layout = QHBoxLayout(self._batch_bar)
        batch_bar_layout.setContentsMargins(0, 0, 0, 0)
        batch_bar_layout.addStretch()
        self._batch_execute_btn = PushButton(FIF.DELETE, "删除选中 (0)")
        self._batch_execute_btn.setFixedWidth(140)
        self._batch_execute_btn.setEnabled(False)
        self._batch_execute_btn.clicked.connect(self._execute_batch_delete)
        batch_bar_layout.addWidget(self._batch_execute_btn)
        self._batch_cancel_btn = PushButton("取消")
        self._batch_cancel_btn.setFixedWidth(80)
        self._batch_cancel_btn.clicked.connect(self._cancel_batch_mode)
        batch_bar_layout.addWidget(self._batch_cancel_btn)
        self._batch_bar.setVisible(False)
        self.vBoxLayout.addWidget(self._batch_bar)

        self.empty_widget = QWidget()
        empty_layout = QVBoxLayout(self.empty_widget)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(12)

        from qfluentwidgets import IconWidget
        empty_icon = IconWidget(FIF.HISTORY)
        empty_icon.setFixedSize(48, 48)
        empty_layout.addWidget(empty_icon, 0, Qt.AlignCenter)

        empty_title = TitleLabel("暂无下载历史")
        empty_title.setAlignment(Qt.AlignCenter)
        empty_title.setStyleSheet("font-size: 20px; font-weight: 600;")
        empty_layout.addWidget(empty_title)

        self.empty_go_btn = PushButton(FIF.HOME, "开始下载")
        self.empty_go_btn.setFixedHeight(36)
        self.empty_go_btn.clicked.connect(self.switch_to_home.emit)
        empty_layout.addSpacing(8)
        empty_layout.addWidget(self.empty_go_btn, 0, Qt.AlignCenter)

        self.empty_widget.hide()
        self.vBoxLayout.addWidget(self.empty_widget)

        self.vBoxLayout.addStretch()

    def refresh(self) -> None:
        """Reload history from disk and refresh the UI with debouncing.
        
        Multiple rapid calls (e.g., from batch downloads) are coalesced
        into a single refresh after 500ms of inactivity.
        """
        self._pending_refresh = True
        self._refresh_timer.start()

    def _update_stats(self) -> None:
        """Update statistics labels from history entries."""
        entries = self._history_manager.get_all()
        total = len(entries)
        total_size = sum(e.get("file_size", 0) for e in entries)
        platforms = set(e.get("platform", "").lower() for e in entries if e.get("platform"))
        self._stat_total.setText(f"总计: {total} 个文件")
        self._stat_size.setText(f"总大小: {format_size(total_size) if total_size else '--'}")
        self._stat_platform.setText(f"平台: {', '.join(sorted(platforms)).upper() if platforms else '--'}")
        avg = total_size // total if total > 0 else 0
        self._stat_avg.setText(f"平均: {format_size(avg) if avg else '--'}")
        # Hide stats if no entries
        self._stats_widget.setVisible(total > 0)

    def _do_refresh(self) -> None:
        """Actually reload history from disk and refresh the UI."""
        self._pending_refresh = False
        self._history_manager.load()
        self._update_stats()
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
            self.empty_widget.show()
            return

        self.empty_widget.hide()

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
                apply_style(meta_label, "font-size: 12px;", "secondary")
                card_layout.addWidget(meta_label)

                card_layout.addWidget(HorizontalSeparator())

                for i, e in enumerate(group):
                    ep_row = QHBoxLayout()
                    ep_row.setSpacing(8)

                    # Batch checkbox for this sub-entry
                    cb = QCheckBox()
                    cb.setVisible(False)
                    tid = e.get("task_id", "")
                    cb.setProperty("task_id", tid)
                    cb.stateChanged.connect(self._update_batch_count)
                    ep_row.addWidget(cb, 0, Qt.AlignLeft)

                    pl = e.get("page_label", "")
                    ep_title = e.get("title", "")[:40]
                    dur = format_duration(e.get("duration", 0)) if e.get("duration") else ""

                    ep_label = CaptionLabel(f"{pl}  {ep_title}")
                    apply_style(ep_label, "font-size: 12px;", "muted")
                    ep_label.setToolTip(e.get("title", ""))
                    ep_label.setMinimumWidth(120)

                    if dur:
                        dur_label = CaptionLabel(dur)
                        apply_style(dur_label, "font-size: 11px;", "muted")
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

        # Apply batch mode visibility to all checkboxes
        self._update_batch_mode_ui()

    def _create_history_card(self, entry: dict) -> HistoryCard:
        """Create a HistoryCard widget from a history entry dict.

        Connects signal handlers for open-folder and delete actions.
        """
        card = HistoryCard(entry)
        card.open_folder_clicked.connect(self._on_open_folder)
        card.delete_clicked.connect(self._delete_entry)
        card.checkbox.stateChanged.connect(self._update_batch_count)
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
        if hasattr(self, 'empty_widget'):
            self.empty_widget.hide()
        self._update_batch_mode_ui()

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

    def _export_csv(self) -> None:
        """Export visible history entries to a CSV file."""
        from PySide6.QtWidgets import QFileDialog

        entries = self._history_manager.get_all() if not self._current_query else self._history_manager.search(self._current_query)
        if not entries:
            InfoBar.warning(
                title="无数据", content="没有可导出的历史记录",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=2000,
                parent=self.window(),
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self.window(), "导出 CSV", "", "CSV Files (*.csv)"
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["task_id", "platform", "title", "quality",
                                 "file_path", "file_size", "duration",
                                 "timestamp", "page_label", "page_count"])
                for e in entries:
                    writer.writerow([
                        e.get("task_id", ""),
                        e.get("platform", ""),
                        e.get("title", ""),
                        e.get("quality", ""),
                        e.get("file_path", ""),
                        e.get("file_size", 0),
                        e.get("duration", 0),
                        e.get("timestamp", 0),
                        e.get("page_label", ""),
                        e.get("page_count", 0),
                    ])
            InfoBar.success(
                title="导出成功", content=f"已导出 {len(entries)} 条记录到 CSV",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=2000,
                parent=self.window(),
            )
        except OSError as e:
            InfoBar.error(
                title="导出失败", content=str(e),
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=3000,
                parent=self.window(),
            )

    def _export_json(self) -> None:
        """Export visible history entries to a JSON file."""
        from PySide6.QtWidgets import QFileDialog

        entries = self._history_manager.get_all() if not self._current_query else self._history_manager.search(self._current_query)
        if not entries:
            InfoBar.warning(
                title="无数据", content="没有可导出的历史记录",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=2000,
                parent=self.window(),
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self.window(), "导出 JSON", "", "JSON Files (*.json)"
        )
        if not path:
            return

        try:
            import json
            with open(path, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2, ensure_ascii=False)
            InfoBar.success(
                title="导出成功", content=f"已导出 {len(entries)} 条记录到 JSON",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=2000,
                parent=self.window(),
            )
        except OSError as e:
            InfoBar.error(
                title="导出失败", content=str(e),
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=3000,
                parent=self.window(),
            )

    def _toggle_batch_mode(self) -> None:
        """Toggle batch delete mode on/off."""
        self._batch_mode = not self._batch_mode
        self._update_batch_mode_ui()
        if self._batch_mode:
            self._batch_toggle_btn.setText("取消批量")
        else:
            self._batch_toggle_btn.setText("批量删除")

    def _update_batch_mode_ui(self) -> None:
        """Show or hide batch mode checkboxes and action bar."""
        for cb in self.container.findChildren(QCheckBox):
            cb.setVisible(self._batch_mode)
            if not self._batch_mode:
                cb.setChecked(False)
        self._batch_bar.setVisible(self._batch_mode)
        self._update_batch_count()

    def _update_batch_count(self) -> None:
        """Recalculate and update the batch delete button text."""
        count = 0
        for cb in self.container.findChildren(QCheckBox):
            if cb.isChecked():
                count += 1
        self._batch_execute_btn.setText(f"删除选中 ({count})")
        self._batch_execute_btn.setEnabled(count > 0)

    def _execute_batch_delete(self) -> None:
        """Delete all checked entries and exit batch mode."""
        task_ids = []
        for cb in self.container.findChildren(QCheckBox):
            if cb.isChecked():
                tid = cb.property("task_id")
                if tid:
                    task_ids.append(tid)
        if not task_ids:
            return

        from qfluentwidgets import MessageBox
        msg = MessageBox(
            "批量删除",
            f"确定要删除选中的 {len(task_ids)} 条记录吗？\n此操作不可撤销。",
            self.window(),
        )
        msg.yesButton.setText("确定")
        msg.cancelButton.setText("取消")
        if not msg.exec():
            return

        deleted = self._history_manager.delete_many(task_ids)
        self._batch_mode = False
        self._batch_toggle_btn.setText("批量删除")
        self._load_history()
        InfoBar.success(
            title="删除成功", content=f"已删除 {deleted} 条记录",
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP_RIGHT, duration=2000,
            parent=self.window(),
        )

    def _cancel_batch_mode(self) -> None:
        """Exit batch mode without deleting anything."""
        self._batch_mode = False
        self._batch_toggle_btn.setText("批量删除")
        self._update_batch_mode_ui()
