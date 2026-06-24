"""
Batch import dialog - paste multiple URLs for batch parsing.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout

from qfluentwidgets import (
    Dialog, CaptionLabel, PrimaryPushButton, FluentIcon as FIF,
    PlainTextEdit,
)

from app.utils.helpers import muted_text_color


class BatchImportDialog(Dialog):
    """Dialog for pasting multiple video URLs (one per line)."""

    def __init__(self, parent=None):
        super().__init__("批量导入", "", parent)
        self.setMinimumWidth(500)
        self.setMaximumWidth(600)
        self.setMinimumHeight(400)

        self.yesButton.setText("开始解析")
        self.cancelButton.setText("取消")

        self._setup_ui()

    def _setup_ui(self):
        self.contentLabel.hide()

        layout = QVBoxLayout()
        layout.setSpacing(8)

        hint = CaptionLabel("粘贴多个视频链接，每个链接一行：")
        hint.setStyleSheet(f"font-size: 13px; color: {muted_text_color()};")

        self.text_edit = PlainTextEdit()
        self.text_edit.setPlaceholderText(
            "https://www.bilibili.com/video/BV1xx...\n"
            "https://www.bilibili.com/video/BV2yy...\n"
            "https://www.bilibili.com/video/BV3zz..."
        )
        self.text_edit.setMinimumHeight(200)

        layout.addWidget(hint)
        layout.addWidget(self.text_edit)

        self.vBoxLayout.insertLayout(0, layout)

    def get_urls(self) -> list[str]:
        """Return list of non-empty trimmed URLs from the text input."""
        text = self.text_edit.toPlainText()
        urls = []
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
        return urls
