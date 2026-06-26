from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget

from qfluentwidgets import (
    Dialog, CaptionLabel,
    FluentIcon as FIF, PlainTextEdit,
    TransparentToolButton, isDarkTheme, setCustomStyleSheet,
)

from app.theme import apply_style


class AnimatedCountBadge(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_count = 0

        self.label = CaptionLabel("0")
        self.label.setFixedSize(40, 22)
        self.label.setAlignment(Qt.AlignCenter)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)

    def set_count(self, count: int):
        if count == self._current_count:
            return
        self._current_count = count
        text = f"{count}" if count > 0 else "0"
        self.label.setText(text)

    def reset(self):
        self._current_count = 0
        self.label.setText("0")

class StatusLabel(CaptionLabel):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self._fade_timer = QTimer(self)
        self._fade_timer.setSingleShot(True)
        self._fade_timer.timeout.connect(lambda: self.setVisible(False))

    def show_message(self, text: str, duration_ms: int = 2000):
        self.setText(text)
        self.setVisible(True)
        self._fade_timer.start(duration_ms)


class BatchImportDialog(Dialog):

    def __init__(self, parent=None):
        super().__init__("批量导入链接", "", parent)
        self.setMinimumWidth(540)
        self.setMaximumWidth(640)
        self.setMinimumHeight(460)

        self.yesButton.setText("开始解析")
        self.cancelButton.setText("取消")
        self.yesButton.setIcon(FIF.DOWNLOAD)

        # Hide default Dialog labels — we build custom UI
        self.titleLabel.hide()
        self.contentLabel.hide()
        self.windowTitleLabel.hide()
        # Tighten button area — transparent, no fixed height, no top margin to touch text edit
        self.buttonGroup.setStyleSheet("background: transparent; border: none;")
        self.buttonGroup.setMinimumHeight(0)
        self.buttonGroup.setMaximumHeight(16777215)
        self.buttonLayout.setContentsMargins(24, 4, 24, 8)

        self._setup_ui()
        # Our layout stretches to fill; collapse empty textLayout (margins+spacing→0, stretch→0)
        self.vBoxLayout.setStretch(0, 1)
        for i in range(self.vBoxLayout.count()):
            item = self.vBoxLayout.itemAt(i)
            if item and item.layout() is not None and i != 0:
                empty = item.layout()
                empty.setContentsMargins(0, 0, 0, 0)
                empty.setSpacing(0)
                self.vBoxLayout.setStretch(i, 0)
                break
        self._update_count()

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(2)

        paste_btn = TransparentToolButton(FIF.PASTE)
        paste_btn.setToolTip("从剪贴板粘贴链接")
        paste_btn.clicked.connect(self._paste_from_clipboard)

        clear_btn = TransparentToolButton(FIF.DELETE)
        clear_btn.setToolTip("清空所有已输入的链接")
        clear_btn.clicked.connect(self._clear_text)

        dedup_btn = TransparentToolButton(FIF.CANCEL)
        dedup_btn.setToolTip("移除重复的链接")
        dedup_btn.clicked.connect(self._deduplicate)

        self.status_label = StatusLabel()
        apply_style(self.status_label, color="secondary")

        self.count_badge = AnimatedCountBadge()

        toolbar.addWidget(paste_btn)
        toolbar.addWidget(clear_btn)
        toolbar.addWidget(dedup_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.status_label)
        toolbar.addSpacing(4)
        toolbar.addWidget(self.count_badge)

        layout.addLayout(toolbar)

        self.text_edit = PlainTextEdit()
        self.text_edit.setPlaceholderText(
            "粘贴 Bilibili 视频链接，一行一个\n\n"
            "例如:\n"
            "https://www.bilibili.com/video/BV1xx411c7mD\n"
            "https://www.bilibili.com/video/BV2yy411d8nE\n"
        )
        self.text_edit.setMinimumHeight(200)
        text_color = "#fff" if isDarkTheme() else "#000"
        placeholder_color = "#999" if isDarkTheme() else "#888"
        self.text_edit.setStyleSheet(f"""
            PlainTextEdit {{
                color: {text_color};
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 14px 16px;
                background-color: transparent;
                font-size: 13px;
            }}
            PlainTextEdit:focus {{
                border: 1px solid transparent;
            }}
        """)

        edit_container = QWidget()
        setCustomStyleSheet(
            edit_container,
            "background-color: transparent; border: 1px solid rgba(0, 0, 0, 0.08); border-radius: 8px;",
            "background-color: transparent; border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 8px;",
        )
        edit_layout = QVBoxLayout(edit_container)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.addWidget(self.text_edit)

        self.text_edit.textChanged.connect(self._update_count)
        layout.addWidget(edit_container, 1)

        self.vBoxLayout.insertLayout(0, layout)

    def _paste_from_clipboard(self):
        from PySide6.QtGui import QGuiApplication
        clipboard = QGuiApplication.clipboard()
        text = clipboard.text()
        if text:
            old_len = len(self.get_urls())
            self.text_edit.setPlainText(
                self.text_edit.toPlainText() + ("\n" if self.text_edit.toPlainText() else "") + text
            )
            new_count = len(self.get_urls())
            added = new_count - old_len
            if added > 0:
                self.status_label.show_message(f"已粘贴 {added} 个链接", 2000)
            else:
                self.status_label.show_message("已粘贴", 1500)

    def _clear_text(self):
        self.text_edit.clear()
        self.status_label.show_message("", 0)

    def _deduplicate(self):
        lines = self.text_edit.toPlainText().splitlines()
        seen = set()
        unique = []
        for line in lines:
            stripped = line.strip()
            if stripped not in seen:
                seen.add(stripped)
                unique.append(line)
        removed = len(lines) - len(unique)
        self.text_edit.setPlainText("\n".join(unique))
        if removed > 0:
            self.status_label.show_message(
                f"已移除 {removed} 个重复链接", 2000
            )
        else:
            self.status_label.show_message("无重复链接", 1500)

    def _update_count(self):
        count = len(self.get_urls())
        self.count_badge.set_count(count)

    def get_urls(self) -> list[str]:
        """Return list of non-empty trimmed URLs from the text input."""
        text = self.text_edit.toPlainText()
        urls = []
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
        return urls
