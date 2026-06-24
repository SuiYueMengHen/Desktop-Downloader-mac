"""
Settings page - theme, download path, account management.
"""
from PySide6.QtCore import Qt, QTime, Signal
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFrame, QFileDialog,
)

from qfluentwidgets import (
    CardWidget, PushButton,
    ComboBox, TitleLabel, CaptionLabel, BodyLabel,
    LineEdit, InfoBar, InfoBarPosition, FluentIcon as FIF,
    HorizontalSeparator, toggleTheme, isDarkTheme, Theme,
    setTheme, Slider, StrongBodyLabel, SpinBox, SwitchButton,
    CheckBox, TimePicker, SmoothScrollArea,
)

from app.config import Config
from app.cookie_manager import CookieManager
from app.ui.login_dialog import BilibiliLoginDialog
from app.utils.helpers import muted_text_color, configure_smooth_scroll


class SettingsPage(SmoothScrollArea):
    """Settings page with configuration options."""

    concurrent_changed = Signal(int)
    speed_limit_changed = Signal(int)
    tray_toggled = Signal(bool)
    schedule_changed = Signal()
    transcode_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = Config()
        self.cookie_manager = CookieManager()
        self._setup_ui()
        configure_smooth_scroll(self)

    def _setup_ui(self):
        """Build the settings page UI."""
        self.container = QFrame(self)
        self.container.setObjectName("settingsContainer")
        self.setWidget(self.container)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        self.vBoxLayout = QVBoxLayout(self.container)
        self.vBoxLayout.setContentsMargins(40, 20, 40, 20)
        self.vBoxLayout.setSpacing(16)

        # Header
        header = TitleLabel("设置")
        header.setStyleSheet("font-size: 28px; font-weight: 600;")
        self.vBoxLayout.addWidget(header)
        self.vBoxLayout.addWidget(HorizontalSeparator())

        # ── Download Settings Card ──
        self._add_download_settings()

        # ── Schedule Settings Card ──
        self._add_schedule_settings()

        # ── Account Card ──
        self._add_account_settings()

        # ── Appearance Card ──
        self._add_appearance_settings()

        # ── About Card ──
        self._add_about()

        self.vBoxLayout.addStretch()

    def _add_download_settings(self):
        """Download path and concurrent settings."""
        card = CardWidget(self.container)
        layout = QVBoxLayout(card)

        title = StrongBodyLabel("下载设置")
        title.setStyleSheet("font-size: 16px;")
        layout.addWidget(title)
        layout.addSpacing(8)

        # Download path
        path_layout = QHBoxLayout()
        path_label = BodyLabel("下载目录:")
        self.path_input = LineEdit()
        self.path_input.setText(self.config.download_path)
        self.path_input.setPlaceholderText("选择下载保存目录")
        self.path_input.setMinimumWidth(300)

        browse_btn = PushButton(FIF.FOLDER, "浏览")
        browse_btn.clicked.connect(self._browse_path)

        self.path_save_btn = PushButton(FIF.SAVE, "保存")
        self.path_save_btn.clicked.connect(self._save_path)

        path_layout.addWidget(path_label)
        path_layout.addWidget(self.path_input, 1)
        path_layout.addWidget(browse_btn)
        path_layout.addWidget(self.path_save_btn)

        layout.addLayout(path_layout)
        layout.addSpacing(8)

        # Max concurrent downloads
        concurrent_layout = QHBoxLayout()
        concurrent_label = BodyLabel("最大并行下载数:")
        self.concurrent_slider = Slider(Qt.Horizontal)
        self.concurrent_slider.setRange(1, 10)
        self.concurrent_slider.setValue(self.config.max_concurrent_downloads)
        self.concurrent_slider.setFixedWidth(200)
        self.concurrent_value_label = CaptionLabel(
            str(self.config.max_concurrent_downloads)
        )

        self.concurrent_slider.valueChanged.connect(
            lambda v: self.concurrent_value_label.setText(str(v))
        )
        self.concurrent_slider.sliderReleased.connect(self._on_concurrent_changed)

        concurrent_layout.addWidget(concurrent_label)
        concurrent_layout.addWidget(self.concurrent_slider)
        concurrent_layout.addWidget(self.concurrent_value_label)
        concurrent_layout.addStretch()

        layout.addLayout(concurrent_layout)

        layout.addSpacing(8)

        # Download speed limit
        speed_layout = QHBoxLayout()
        speed_label = BodyLabel("单任务限速:")
        self.speed_spin = SpinBox()
        self.speed_spin.setRange(0, 102400)
        self.speed_spin.setValue(self.config.download_speed_limit)
        self.speed_spin.setFixedWidth(160)
        self.speed_spin.setSuffix(" KB/s")
        self.speed_spin.setToolTip("0 表示不限速，每个并发任务的下载速度上限")

        speed_note = CaptionLabel("0 = 不限速")
        speed_note.setStyleSheet(f"color: {muted_text_color()};")

        speed_layout.addWidget(speed_label)
        speed_layout.addWidget(self.speed_spin)
        speed_layout.addWidget(speed_note)
        speed_layout.addStretch()

        self.speed_spin.valueChanged.connect(self._on_speed_limit_changed)

        layout.addLayout(speed_layout)

        layout.addSpacing(8)

        # Clipboard monitor toggle
        clip_layout = QHBoxLayout()
        clip_label = BodyLabel("剪贴板监控:")
        self.clipboard_switch = SwitchButton()
        self.clipboard_switch.setOnText("已开启")
        self.clipboard_switch.setOffText("已关闭")
        self.clipboard_switch.setChecked(self.config.clipboard_monitor_enabled)
        clip_note = CaptionLabel("自动检测剪贴板的B站链接并解析")
        clip_note.setStyleSheet(f"color: {muted_text_color()};")

        clip_layout.addWidget(clip_label)
        clip_layout.addWidget(self.clipboard_switch)
        clip_layout.addWidget(clip_note)
        clip_layout.addStretch()

        self.clipboard_switch.checkedChanged.connect(self._on_clipboard_toggled)

        layout.addLayout(clip_layout)

        layout.addSpacing(8)

        # Notification settings
        notif_layout = QHBoxLayout()
        notif_label = BodyLabel("下载完成通知:")
        self.notification_switch = SwitchButton()
        self.notification_switch.setOnText("已开启")
        self.notification_switch.setOffText("已关闭")
        self.notification_switch.setChecked(self.config.notification_enabled)
        notif_note = CaptionLabel("下载完成时弹出系统通知")
        notif_note.setStyleSheet(f"color: {muted_text_color()};")

        notif_layout.addWidget(notif_label)
        notif_layout.addWidget(self.notification_switch)
        notif_layout.addWidget(notif_note)
        notif_layout.addStretch()

        self.notification_switch.checkedChanged.connect(self._on_notification_toggled)

        layout.addLayout(notif_layout)

        # Notification sound toggle (only enabled when notifications are on)
        sound_layout = QHBoxLayout()
        sound_label = BodyLabel("通知提示音:")
        self.sound_switch = SwitchButton()
        self.sound_switch.setOnText("已开启")
        self.sound_switch.setOffText("已关闭")
        self.sound_switch.setChecked(self.config.notification_sound)
        self.sound_switch.setEnabled(self.config.notification_enabled)
        sound_note = CaptionLabel("通知时播放提示音")
        sound_note.setStyleSheet(f"color: {muted_text_color()};")

        sound_layout.addWidget(sound_label)
        sound_layout.addWidget(self.sound_switch)
        sound_layout.addWidget(sound_note)
        sound_layout.addStretch()

        self.sound_switch.checkedChanged.connect(self._on_sound_toggled)

        layout.addLayout(sound_layout)

        # Minimize to tray toggle
        layout.addSpacing(8)
        tray_layout = QHBoxLayout()
        tray_label = BodyLabel("最小化到系统托盘:")
        self.tray_switch = SwitchButton()
        self.tray_switch.setOnText("已开启")
        self.tray_switch.setOffText("已关闭")
        self.tray_switch.setChecked(self.config.minimize_to_tray)
        tray_note = CaptionLabel("关闭窗口时最小化到托盘，后台继续下载")
        tray_note.setStyleSheet(f"color: {muted_text_color()};")

        tray_layout.addWidget(tray_label)
        tray_layout.addWidget(self.tray_switch)
        tray_layout.addWidget(tray_note)
        tray_layout.addStretch()

        self.tray_switch.checkedChanged.connect(self._on_tray_toggled)

        layout.addLayout(tray_layout)

        # Post-download transcode
        layout.addSpacing(8)
        transcode_layout = QHBoxLayout()
        transcode_label = BodyLabel("下载完成后转码:")
        self.transcode_combo = ComboBox()
        self.transcode_combo.addItem("不转码", userData="none")
        self.transcode_combo.addItem("H.264 (兼容性好)", userData="h264")
        self.transcode_combo.addItem("H.265 (体积更小)", userData="h265")
        current_transcode = self.config.post_download_transcode
        idx = self.transcode_combo.findData(current_transcode)
        if idx >= 0:
            self.transcode_combo.setCurrentIndex(idx)
        transcode_note = CaptionLabel("下载完成后用ffmpeg重新编码")
        transcode_note.setStyleSheet(f"color: {muted_text_color()};")

        transcode_layout.addWidget(transcode_label)
        transcode_layout.addWidget(self.transcode_combo)
        transcode_layout.addWidget(transcode_note)
        transcode_layout.addStretch()

        self.transcode_combo.currentIndexChanged.connect(self._on_transcode_changed)

        layout.addLayout(transcode_layout)

        self.vBoxLayout.addWidget(card)

    def _on_transcode_changed(self, index: int):
        data = self.transcode_combo.itemData(index)
        self.config.post_download_transcode = data or "none"
        self.transcode_changed.emit(data or "none")

    def _on_tray_toggled(self, enabled: bool):
        self.config.minimize_to_tray = enabled

    def _on_speed_limit_changed(self, value: int):
        self.config.download_speed_limit = value
        self.speed_limit_changed.emit(value)

    def _on_clipboard_toggled(self, enabled: bool):
        self.config.clipboard_monitor_enabled = enabled
        mw = self.window()
        if hasattr(mw, 'clipboard_monitor'):
            mw.clipboard_monitor.set_enabled(enabled)

    def _on_notification_toggled(self, enabled: bool):
        self.config.notification_enabled = enabled
        self.sound_switch.setEnabled(enabled)

    def _on_sound_toggled(self, enabled: bool):
        self.config.notification_sound = enabled

    # ── Schedule Settings ──

    def _add_schedule_settings(self):
        card = CardWidget(self.container)
        layout = QVBoxLayout(card)

        title = StrongBodyLabel("下载调度")
        title.setStyleSheet("font-size: 16px;")
        layout.addWidget(title)
        layout.addSpacing(8)

        # Enable toggle
        sched_layout = QHBoxLayout()
        sched_label = BodyLabel("启用下载时段:")
        self.schedule_switch = SwitchButton()
        self.schedule_switch.setOnText("已启用")
        self.schedule_switch.setOffText("已禁用")
        self.schedule_switch.setChecked(self.config.schedule_enabled)
        sched_note = CaptionLabel("只在指定时段内下载，其他时间自动暂停")
        sched_note.setStyleSheet(f"color: {muted_text_color()};")

        sched_layout.addWidget(sched_label)
        sched_layout.addWidget(self.schedule_switch)
        sched_layout.addWidget(sched_note)
        sched_layout.addStretch()

        self.schedule_switch.checkedChanged.connect(self._on_schedule_enabled_changed)
        layout.addLayout(sched_layout)

        layout.addSpacing(8)

        # Time range
        time_layout = QHBoxLayout()
        time_label = BodyLabel("下载时段:")

        start_parts = self.config.schedule_start.split(":")
        self.start_picker = TimePicker(self)
        self.start_picker.setTime(QTime(int(start_parts[0]), int(start_parts[1]) if len(start_parts) > 1 else 0))

        sep_label = CaptionLabel(" 至 ")
        sep_label.setStyleSheet("font-size: 14px;")

        end_parts = self.config.schedule_end.split(":")
        self.end_picker = TimePicker(self)
        self.end_picker.setTime(QTime(int(end_parts[0]), int(end_parts[1]) if len(end_parts) > 1 else 0))

        self.start_picker.timeChanged.connect(self._on_schedule_time_changed)
        self.end_picker.timeChanged.connect(self._on_schedule_time_changed)

        time_layout.addWidget(time_label)
        time_layout.addWidget(self.start_picker)
        time_layout.addWidget(sep_label)
        time_layout.addWidget(self.end_picker)
        time_layout.addStretch()

        layout.addLayout(time_layout)

        layout.addSpacing(8)

        # Day of week
        day_label = BodyLabel("生效日期:")
        layout.addWidget(day_label)

        days_layout = QHBoxLayout()
        day_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        self.day_checkboxes = []
        saved_days = self.config.schedule_days
        for i, name in enumerate(day_names):
            cb = CheckBox(name)
            cb.setChecked(i in saved_days)
            cb.stateChanged.connect(self._on_schedule_days_changed)
            days_layout.addWidget(cb)
            self.day_checkboxes.append(cb)
        days_layout.addStretch()
        layout.addLayout(days_layout)

        self.vBoxLayout.addWidget(card)

    def _on_schedule_enabled_changed(self, enabled: bool):
        self.config.schedule_enabled = enabled
        self.schedule_changed.emit()

    def _on_schedule_time_changed(self):
        start_h = self.start_picker.hour()
        start_m = self.start_picker.minute()
        end_h = self.end_picker.hour()
        end_m = self.end_picker.minute()
        self.config.schedule_start = f"{start_h:02d}:{start_m:02d}"
        self.config.schedule_end = f"{end_h:02d}:{end_m:02d}"
        self.schedule_changed.emit()

    def _on_schedule_days_changed(self):
        days = []
        for i, cb in enumerate(self.day_checkboxes):
            if cb.isChecked():
                days.append(i)
        self.config.schedule_days = days
        self.schedule_changed.emit()

    def _add_account_settings(self):
        """Account/cookie management card."""
        card = CardWidget(self.container)
        layout = QVBoxLayout(card)

        title = StrongBodyLabel("账号管理")
        title.setStyleSheet("font-size: 16px;")
        layout.addWidget(title)
        layout.addSpacing(8)

        # Bilibili
        bilibili_layout = QHBoxLayout()
        bilibili_label = BodyLabel("Bilibili:")

        self.bilibili_status = CaptionLabel(
            "已登录" if self.cookie_manager.is_bilibili_logged_in() else "未登录"
        )
        self.bilibili_status.setStyleSheet(
            "color: #27ae60; font-size: 13px;"
            if self.cookie_manager.is_bilibili_logged_in()
            else "color: #e74c3c; font-size: 13px;"
        )

        self.bilibili_login_btn = PushButton(FIF.PEOPLE, "登录/管理")
        self.bilibili_login_btn.clicked.connect(self._open_bilibili_login)

        self.bilibili_logout_btn = PushButton(FIF.DELETE, "清除Cookie")
        self.bilibili_logout_btn.clicked.connect(self._clear_bilibili_cookie)
        self.bilibili_logout_btn.setVisible(self.cookie_manager.is_bilibili_logged_in())

        bilibili_layout.addWidget(bilibili_label)
        bilibili_layout.addWidget(self.bilibili_status)
        bilibili_layout.addStretch()
        bilibili_layout.addWidget(self.bilibili_login_btn)
        bilibili_layout.addWidget(self.bilibili_logout_btn)

        layout.addLayout(bilibili_layout)

        self.vBoxLayout.addWidget(card)

    def _add_appearance_settings(self):
        """Theme and appearance card."""
        card = CardWidget(self.container)
        layout = QVBoxLayout(card)

        title = StrongBodyLabel("外观")
        title.setStyleSheet("font-size: 16px;")
        layout.addWidget(title)
        layout.addSpacing(8)

        theme_layout = QHBoxLayout()
        theme_label = BodyLabel("主题模式:")
        self.theme_combo = ComboBox()
        self.theme_combo.addItems(["自动", "浅色", "深色"])
        theme_map = {"auto": "自动", "light": "浅色", "dark": "深色"}
        current_theme = self.config.theme_mode
        self.theme_combo.setCurrentText(theme_map.get(current_theme, "自动"))

        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)

        # Quick toggle button
        self.theme_toggle_btn = PushButton(FIF.PALETTE, "快速切换")
        self.theme_toggle_btn.clicked.connect(self._on_quick_toggle)

        theme_layout.addWidget(theme_label)
        theme_layout.addWidget(self.theme_combo)
        theme_layout.addSpacing(8)
        theme_layout.addWidget(self.theme_toggle_btn)
        theme_layout.addStretch()

        layout.addLayout(theme_layout)

        self.vBoxLayout.addWidget(card)

    def _add_about(self):
        """About section."""
        card = CardWidget(self.container)
        layout = QVBoxLayout(card)

        title = StrongBodyLabel("关于")
        title.setStyleSheet("font-size: 16px;")
        layout.addWidget(title)
        layout.addSpacing(8)

        from app import __version__ as app_ver
        about_text = CaptionLabel(
            f"Desktop Downloader {app_ver}\n"
            "基于 PySide6 + QFluentWidgets 构建\n"
            "支持 Bilibili 视频下载\n\n"
            "注意: 请尊重平台版权，仅下载个人学习用途的内容"
        )
        about_text.setStyleSheet(f"font-size: 13px; color: {muted_text_color()}; line-height: 1.5;")
        layout.addWidget(about_text)

        self.vBoxLayout.addWidget(card)

    # ── Slots ──

    def _save_path(self):
        """Save manually entered download path."""
        path = self.path_input.text().strip()
        if path:
            self.config.download_path = path
            InfoBar.success(
                title="已保存",
                content=f"下载目录: {path}",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=3000,
                parent=self.window(),
            )

    def _browse_path(self):
        """Open directory picker for download path."""
        path = QFileDialog.getExistingDirectory(
            self, "选择下载目录", self.path_input.text()
        )
        if path:
            self.path_input.setText(path)
            self.config.download_path = path
            InfoBar.success(
                title="已更新",
                content=f"下载目录: {path}",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3000,
                parent=self.window(),
            )

    def _on_concurrent_changed(self):
        """Handle concurrent downloads slider change."""
        value = self.concurrent_slider.value()
        self.config.max_concurrent_downloads = value
        self.concurrent_changed.emit(value)

    def _on_theme_changed(self, text: str):
        """Handle theme combo change."""
        theme_map = {"自动": "auto", "浅色": "light", "深色": "dark"}
        mode = theme_map.get(text, "auto")
        self.config.theme_mode = mode

        if mode == "dark":
            setTheme(Theme.DARK)
        elif mode == "light":
            setTheme(Theme.LIGHT)
        else:
            # Auto - use system theme
            setTheme(Theme.AUTO)

    def _on_quick_toggle(self):
        """Quick toggle between light and dark themes."""
        toggleTheme()
        # Sync combo box to match current theme
        new_mode = "dark" if isDarkTheme() else "light"
        self.config.theme_mode = new_mode
        theme_map_rev = {"dark": "深色", "light": "浅色"}
        self.theme_combo.setCurrentText(theme_map_rev.get(new_mode, "自动"))

    def _open_bilibili_login(self):
        """Open Bilibili login dialog."""
        dialog = BilibiliLoginDialog(self.window())
        dialog.login_successful.connect(self._on_bilibili_login_success)
        dialog.exec()

    def _on_bilibili_login_success(self, creds: dict):
        """Handle successful Bilibili login."""
        self.bilibili_status.setText("已登录")
        self.bilibili_status.setStyleSheet("color: #27ae60; font-size: 13px;")
        self.bilibili_logout_btn.setVisible(True)
        # Refresh platform credentials
        mw = self.window()
        if hasattr(mw, 'bilibili') and hasattr(mw.bilibili, 'refresh_credential'):
            mw.bilibili.refresh_credential()

    def _clear_bilibili_cookie(self):
        """Clear Bilibili credentials."""
        self.cookie_manager.clear_bilibili()
        self.bilibili_status.setText("未登录")
        self.bilibili_status.setStyleSheet("color: #e74c3c; font-size: 13px;")
        self.bilibili_logout_btn.setVisible(False)
        # Refresh platform credentials
        mw = self.window()
        if hasattr(mw, 'bilibili') and hasattr(mw.bilibili, 'refresh_credential'):
            mw.bilibili.refresh_credential()

        InfoBar.success(
            title="已清除",
            content="Bilibili Cookie 已清除",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=3000,
            parent=self.window(),
        )
