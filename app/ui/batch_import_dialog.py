"""
Batch import dialog - paste multiple URLs for batch parsing.
Redesigned with URL count badge, paste detection, clear/dedup, and better styling.
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout

from qfluentwidgets import (
    Dialog, CaptionLabel, PrimaryPushButton, PushButton,
    FluentIcon as FIF, PlainTextEdit, BodyLabel,
    InfoBar, InfoBarPosition, HorizontalSeparator,
)

from app.utils.helpers import muted_text_color, secondary_text_color


class BatchImportDialog(Dialog):
    """Dialog for pasting multiple video URLs (one per line)."""

    def __init__(self, parent=None):
        super().__init__("批量导入链接", "", parent)
        self.setMinimumWidth(540)
        self.setMaximumWidth(640)
        self.setMinimumHeight(440)

        self.yesButton.setText("开始解析")
        self.cancelButton.setText("取消")

        self._setup_ui()
        self._connect_signals()
        self._update_count()

    def _setup_ui(self):
        self.contentLabel.hide()

        layout = QVBoxLayout()
        layout.setSpacing(8)

        # ── Header area ──
        header_row = QHBoxLayout()
        hint = BodyLabel("粘贴多个视频链接，每个链接一行：")
        hint.setStyleSheet("font-size: 14px;")

        self.count_badge = CaptionLabel("0 个链接")
        self.count_badge.setStyleSheet(
            "background-color: #6c5ce7; color: white; "
            "padding: 2px 12px; border-radius: 10px; font-size: 11px;"
        )
        self.count_badge.setVisible(False)

        header_row.addWidget(hint)
        header_row.addStretch()
        header_row.addWidget(self.count_badge)
        layout.addLayout(header_row)

        # ── Toolbar ──
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        paste_btn = PrimaryPushButton(FIF.PASTE, "粘贴")
        paste_btn.setToolTip("从剪贴板粘贴链接")
        paste_btn.clicked.connect(self._paste_from_clipboard)

        clear_btn = PushButton(FIF.DELETE, "清空")
        clear_btn.setToolTip("清空所有已输入的链接")
        clear_btn.clicked.connect(self._clear_text)

        dedup_btn = PushButton(FIF.CANCEL, "去重")
        dedup_btn.setToolTip("移除重复的链接")
        dedup_btn.clicked.connect(self._deduplicate)

        self.paste_hint = CaptionLabel("")
        self.paste_hint.setStyleSheet(f"color: {secondary_text_color()};")

        toolbar.addWidget(paste_btn)
        toolbar.addWidget(clear_btn)
        toolbar.addWidget(dedup_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.paste_hint)
        layout.addLayout(toolbar)

        layout.addSpacing(4)

        # ── Text edit ──
        self.text_edit = PlainTextEdit()
        self.text_edit.setPlaceholderText(
            "粘贴 Bilibili 视频链接，一行一个\n\n"
            "例如:\n"
            "https://www.bilibili.com/video/BV1xx411c7mD\n"
            "https://www.bilibili.com/video/BV2yy411d8nE\n"
            "https://www.bilibili.com/video/BV3zz411e9oF\n\n"
            "支持格式:\n"
            "  • bilibili.com/video/BV...\n"
            "  • b23.tv/XXXXX (短链接)"
        )
        self.text_edit.setMinimumHeight(200)

        # Auto-count via signal
        self.text_edit.textChanged.connect(self._update_count)

        layout.addWidget(self.text_edit, 1)

        # ── Footer hint ──
        layout.addSpacing(4)
        footer = CaptionLabel("以 # 开头的行会被忽略（注释行）")
        footer.setStyleSheet(f"color: {muted_text_color()};")
        layout.addWidget(footer)

        self.vBoxLayout.insertLayout(0, layout)

    def _connect_signals(self):
        pass  # text_changed connected inline

    def _paste_from_clipboard(self):
        from PySide6.QtGui import QGuiApplication
        clipboard = QGuiApplication.clipboard()
        text = clipboard.text()
        if text:
            self.text_edit.setPlainText(
                self.text_edit.toPlainText() + ("\n" if self.text_edit.toPlainText() else "") + text
            )
            self.paste_hint.setText("已粘贴")
            QTimer.singleShot(2000, lambda: self.paste_hint.setText(""))

    def _clear_text(self):
        self.text_edit.clear()
        self.paste_hint.setText("")

    def _deduplicate(self):
        lines = self.text_edit.toPlainText().splitlines()
        seen = set()
        unique = []
        for line in lines:
            stripped = line.strip()
            if stripped not in seen:
                seen.add(stripped)
                unique.append(line)
        self.text_edit.setPlainText("\n".join(unique))
        self.paste_hint.setText(f"已移除 {len(lines) - len(unique)} 个重复链接")

    def _update_count(self):
        text = self.text_edit.toPlainText()
        urls = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
        count = len(urls)
        if count > 0:
            self.count_badge.setText(f"{count} 个链接")
            self.count_badge.setVisible(True)
        else:
            self.count_badge.setVisible(False)

    def get_urls(self) -> list[str]:
        """Return list of non-empty trimmed URLs from the text input."""
        text = self.text_edit.toPlainText()
        urls = []
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
        return urls
