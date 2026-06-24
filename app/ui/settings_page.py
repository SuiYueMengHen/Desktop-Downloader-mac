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
from app.utils.helpers import muted_text_color, secondary_text_color, configure_smooth_scroll


class SettingsPage(SmoothScrollArea):
    """Settings page with configuration options."""

    concurrent_changed = Signal(int)
    speed_limit_changed = Signal(int)
    tray_toggled = Signal(bool)
    schedule_changed = Signal()
    transcode_changed = Signal(str)

    _LABEL_WIDTH = 140

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = Config()
        self.cookie_manager = CookieManager()
        self._setup_ui()
        configure_smooth_scroll(self)

    # ── Layout helpers ──

    def _row(self, *widgets, stretch=True):
        row = QHBoxLayout()
        row.setSpacing(8)
        for w in widgets:
            row.addWidget(w)
        if stretch:
            row.addStretch()
        return row

    def _label(self, text: str, width: int = None) -> BodyLabel:
        lbl = BodyLabel(text)
        if width:
            lbl.setFixedWidth(width)
        return lbl

    def _note(self, text: str) -> CaptionLabel:
        n = CaptionLabel(text)
        n.setStyleSheet(f"color: {muted_text_color()};")
        return n

    def _card_title(self, text: str) -> StrongBodyLabel:
        t = StrongBodyLabel(text)
        t.setStyleSheet("font-size: 16px;")
        return t

    # ── Build UI ──

    def _setup_ui(self):
        self.container = QFrame(self)
        self.container.setObjectName("settingsContainer")
        self.setWidget(self.container)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        self.vBoxLayout = QVBoxLayout(self.container)
        self.vBoxLayout.setContentsMargins(40, 20, 40, 20)
        self.vBoxLayout.setSpacing(16)

        header = TitleLabel("设置")
        header.setStyleSheet("font-size: 28px; font-weight: 600;")
        self.vBoxLayout.addWidget(header)
        self.vBoxLayout.addWidget(HorizontalSeparator())

        self._add_download_card()
        self._add_schedule_card()
        self._add_account_card()
        self._add_appearance_card()
        self._add_about_card()

        self.vBoxLayout.addStretch()

    # ══════════════════════════════════════════════════
    #  下载设置
    # ══════════════════════════════════════════════════

    def _add_download_card(self):
        card = CardWidget(self.container)
        layout = QVBoxLayout(card)
        layout.setSpacing(12)

        layout.addWidget(self._card_title("下载设置"))

        # ── Download path ──
        path_row = QHBoxLayout()
        path_row.addWidget(self._label("下载目录:", self._LABEL_WIDTH))
        self.path_input = LineEdit()
        self.path_input.setText(self.config.download_path)
        self.path_input.setMinimumWidth(300)
        self.path_input.returnPressed.connect(self._save_path)
        browse_btn = PushButton(FIF.FOLDER, "浏览")
        browse_btn.clicked.connect(self._browse_path)
        path_row.addWidget(self.path_input, 1)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        # ── Concurrent downloads ──
        conc_row = QHBoxLayout()
        conc_row.addWidget(self._label("并行下载数:", self._LABEL_WIDTH))
        self.concurrent_slider = Slider(Qt.Horizontal)
        self.concurrent_slider.setRange(1, 10)
        self.concurrent_slider.setValue(self.config.max_concurrent_downloads)
        self.concurrent_slider.setFixedWidth(200)
        self.concurrent_value_label = CaptionLabel(str(self.config.max_concurrent_downloads))
        self.concurrent_slider.valueChanged.connect(
            lambda v: self.concurrent_value_label.setText(str(v))
        )
        self.concurrent_slider.sliderReleased.connect(self._on_concurrent_changed)
        conc_row.addWidget(self.concurrent_slider)
        conc_row.addWidget(self.concurrent_value_label)
        conc_row.addWidget(self._note("同时进行的下载任务数"))
        conc_row.addStretch()
        layout.addLayout(conc_row)

        # ── Speed limit ──
        speed_row = QHBoxLayout()
        speed_row.addWidget(self._label("单任务限速:", self._LABEL_WIDTH))
        self.speed_spin = SpinBox()
        self.speed_spin.setRange(0, 102400)
        self.speed_spin.setValue(self.config.download_speed_limit)
        self.speed_spin.setFixedWidth(160)
        self.speed_spin.setSuffix(" KB/s")
        self.speed_spin.setToolTip("0 = 不限速")
        self.speed_spin.valueChanged.connect(self._on_speed_limit_changed)
        speed_row.addWidget(self.speed_spin)
        speed_row.addWidget(self._note("0 表示不限速"))
        speed_row.addStretch()
        layout.addLayout(speed_row)

        # ── Post-download transcode ──
        tc_row = QHBoxLayout()
        tc_row.addWidget(self._label("下载后转码:", self._LABEL_WIDTH))
        self.transcode_combo = ComboBox()
        self.transcode_combo.addItem("不转码", userData="none")
        self.transcode_combo.addItem("H.264 (兼容性好)", userData="h264")
        self.transcode_combo.addItem("H.265 (体积更小)", userData="h265")
        idx = self.transcode_combo.findData(self.config.post_download_transcode)
        if idx >= 0:
            self.transcode_combo.setCurrentIndex(idx)
        self.transcode_combo.currentIndexChanged.connect(self._on_transcode_changed)
        tc_row.addWidget(self.transcode_combo)
        tc_row.addWidget(self._note("用 FFmpeg 重新编码"))
        tc_row.addStretch()
        layout.addLayout(tc_row)

        # divider
        layout.addSpacing(4)
        layout.addWidget(HorizontalSeparator())
        layout.addSpacing(4)

        # ── Clipboard monitor ──
        clip_row = self._row(
            self._label("剪贴板监控:", self._LABEL_WIDTH),
            self._switch("clipboard_switch", self.config.clipboard_monitor_enabled,
                         self._on_clipboard_toggled),
            self._note("自动检测B站链接并解析"),
        )
        layout.addLayout(clip_row)

        # ── Notification ──
        notif_row = self._row(
            self._label("下载完成通知:", self._LABEL_WIDTH),
            self._switch("notification_switch", self.config.notification_enabled,
                         self._on_notification_toggled),
            self._note("弹出系统通知"),
        )
        layout.addLayout(notif_row)

        # ── Notification sound ──
        sound_row = self._row(
            self._label("通知提示音:", self._LABEL_WIDTH),
            self._switch("sound_switch", self.config.notification_sound,
                         self._on_sound_toggled),
            self._note("通知时播放提示音"),
        )
        self.sound_switch.setEnabled(self.config.notification_enabled)
        layout.addLayout(sound_row)

        # ── Minimize to tray ──
        tray_row = self._row(
            self._label("最小化到托盘:", self._LABEL_WIDTH),
            self._switch("tray_switch", self.config.minimize_to_tray,
                         self._on_tray_toggled),
            self._note("关闭窗口时后台继续下载"),
        )
        layout.addLayout(tray_row)

        self.vBoxLayout.addWidget(card)

    # ══════════════════════════════════════════════════
    #  下载调度
    # ══════════════════════════════════════════════════

    def _add_schedule_card(self):
        card = CardWidget(self.container)
        layout = QVBoxLayout(card)
        layout.setSpacing(12)

        layout.addWidget(self._card_title("下载调度"))

        # ── Enable toggle ──
        sched_row = self._row(
            self._label("启用下载时段:", self._LABEL_WIDTH),
            self._switch("schedule_switch", self.config.schedule_enabled,
                         self._on_schedule_enabled_changed),
            self._note("只在指定时段下载，其他时间自动暂停"),
        )
        layout.addLayout(sched_row)
        layout.addSpacing(4)

        # ── Time range ──
        time_row = QHBoxLayout()
        time_row.addWidget(self._label("下载时段:", self._LABEL_WIDTH))
        start_parts = self.config.schedule_start.split(":")
        self.start_picker = TimePicker(self)
        self.start_picker.setTime(QTime(int(start_parts[0]),
                                        int(start_parts[1]) if len(start_parts) > 1 else 0))
        sep = CaptionLabel(" 至 ")
        sep.setStyleSheet("font-size: 14px;")
        end_parts = self.config.schedule_end.split(":")
        self.end_picker = TimePicker(self)
        self.end_picker.setTime(QTime(int(end_parts[0]),
                                      int(end_parts[1]) if len(end_parts) > 1 else 0))
        self.start_picker.timeChanged.connect(self._on_schedule_time_changed)
        self.end_picker.timeChanged.connect(self._on_schedule_time_changed)
        time_row.addWidget(self.start_picker)
        time_row.addWidget(sep)
        time_row.addWidget(self.end_picker)
        time_row.addStretch()
        layout.addLayout(time_row)

        # ── Day of week ──
        day_row = QHBoxLayout()
        day_row.addWidget(self._label("生效日期:", self._LABEL_WIDTH))
        day_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        self.day_checkboxes = []
        saved_days = self.config.schedule_days
        for i, name in enumerate(day_names):
            cb = CheckBox(name)
            cb.setChecked(i in saved_days)
            cb.stateChanged.connect(self._on_schedule_days_changed)
            day_row.addWidget(cb)
            self.day_checkboxes.append(cb)
        day_row.addStretch()
        layout.addLayout(day_row)

        self.vBoxLayout.addWidget(card)

    # ══════════════════════════════════════════════════
    #  账号管理
    # ══════════════════════════════════════════════════

    def _add_account_card(self):
        card = CardWidget(self.container)
        layout = QVBoxLayout(card)
        layout.setSpacing(12)

        layout.addWidget(self._card_title("账号管理"))

        bili_row = QHBoxLayout()
        bili_row.addWidget(self._label("Bilibili:", self._LABEL_WIDTH))
        self.bilibili_status = CaptionLabel(
            "已登录" if self.cookie_manager.is_bilibili_logged_in() else "未登录"
        )
        self.bilibili_status.setStyleSheet(
            "color: #27ae60; font-size: 13px;"
            if self.cookie_manager.is_bilibili_logged_in()
            else "color: #e74c3c; font-size: 13px;"
        )
        self.bilibili_login_btn = PushButton(FIF.PEOPLE, "登录")
        self.bilibili_login_btn.clicked.connect(self._open_bilibili_login)
        self.bilibili_logout_btn = PushButton(FIF.DELETE, "清除Cookie")
        self.bilibili_logout_btn.clicked.connect(self._clear_bilibili_cookie)
        self.bilibili_logout_btn.setVisible(self.cookie_manager.is_bilibili_logged_in())
        bili_row.addWidget(self.bilibili_status)
        bili_row.addStretch()
        bili_row.addWidget(self.bilibili_login_btn)
        bili_row.addWidget(self.bilibili_logout_btn)
        layout.addLayout(bili_row)

        self.vBoxLayout.addWidget(card)

    # ══════════════════════════════════════════════════
    #  外观
    # ══════════════════════════════════════════════════

    def _add_appearance_card(self):
        card = CardWidget(self.container)
        layout = QVBoxLayout(card)
        layout.setSpacing(12)

        layout.addWidget(self._card_title("外观"))

        theme_row = QHBoxLayout()
        theme_row.addWidget(self._label("主题模式:", self._LABEL_WIDTH))
        self.theme_combo = ComboBox()
        self.theme_combo.addItems(["自动", "浅色", "深色"])
        theme_map = {"auto": "自动", "light": "浅色", "dark": "深色"}
        self.theme_combo.setCurrentText(theme_map.get(self.config.theme_mode, "自动"))
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        self.theme_toggle_btn = PushButton(FIF.PALETTE, "快速切换")
        self.theme_toggle_btn.clicked.connect(self._on_quick_toggle)
        theme_row.addWidget(self.theme_combo)
        theme_row.addSpacing(8)
        theme_row.addWidget(self.theme_toggle_btn)
        theme_row.addStretch()
        layout.addLayout(theme_row)

        startup_row = self._row(
            self._label("启动动画:", self._LABEL_WIDTH),
            self._switch("startup_switch", self.config.startup_animation,
                         self._on_startup_animation_toggled),
            self._note("应用启动时显示动画效果"),
        )
        layout.addLayout(startup_row)

        self.vBoxLayout.addWidget(card)

    # ══════════════════════════════════════════════════
    #  关于
    # ══════════════════════════════════════════════════

    def _add_about_card(self):
        card = CardWidget(self.container)
        layout = QVBoxLayout(card)
        layout.setSpacing(12)

        layout.addWidget(self._card_title("关于"))

        from app import __version__ as app_ver
        txt = CaptionLabel(
            f"Desktop Downloader {app_ver}\n"
            "基于 PySide6 + QFluentWidgets 构建\n"
            "支持 Bilibili 视频下载\n\n"
            "注意: 请尊重平台版权，仅下载个人学习用途的内容"
        )
        txt.setStyleSheet(f"color: {muted_text_color()}; font-size: 13px;")
        layout.addWidget(txt)

        self.vBoxLayout.addWidget(card)

    # ── Switch helper ──

    def _switch(self, attr: str, default: bool, slot) -> SwitchButton:
        s = SwitchButton()
        s.setOnText("已开启")
        s.setOffText("已关闭")
        s.setChecked(default)
        s.checkedChanged.connect(slot)
        setattr(self, attr, s)
        return s

    # ── Slots ──

    def _on_transcode_changed(self, index: int):
        data = self.transcode_combo.itemData(index)
        self.config.post_download_transcode = data or "none"
        self.transcode_changed.emit(data or "none")

    def _on_tray_toggled(self, enabled: bool):
        self.config.minimize_to_tray = enabled
        self.tray_toggled.emit(enabled)

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

    def _on_startup_animation_toggled(self, enabled: bool):
        self.config.startup_animation = enabled

    def _on_schedule_enabled_changed(self, enabled: bool):
        self.config.schedule_enabled = enabled
        self.schedule_changed.emit()

    def _on_schedule_time_changed(self):
        self.config.schedule_start = f"{self.start_picker.hour():02d}:{self.start_picker.minute():02d}"
        self.config.schedule_end = f"{self.end_picker.hour():02d}:{self.end_picker.minute():02d}"
        self.schedule_changed.emit()

    def _on_schedule_days_changed(self):
        days = [i for i, cb in enumerate(self.day_checkboxes) if cb.isChecked()]
        self.config.schedule_days = days
        self.schedule_changed.emit()

    def _browse_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择下载目录", self.path_input.text())
        if path:
            self.path_input.setText(path)
            self.config.download_path = path
            InfoBar.success(
                title="已更新", content=f"下载目录: {path}",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=3000,
                parent=self.window(),
            )

    def _save_path(self):
        path = self.path_input.text().strip()
        if path:
            self.config.download_path = path

    def _on_concurrent_changed(self):
        value = self.concurrent_slider.value()
        self.config.max_concurrent_downloads = value
        self.concurrent_changed.emit(value)

    def _on_theme_changed(self, text: str):
        mode = {"自动": "auto", "浅色": "light", "深色": "dark"}.get(text, "auto")
        self.config.theme_mode = mode
        if mode == "dark":
            setTheme(Theme.DARK, lazy=True)
        elif mode == "light":
            setTheme(Theme.LIGHT, lazy=True)
        else:
            setTheme(Theme.AUTO, lazy=True)

    def _on_quick_toggle(self):
        toggleTheme()
        new_mode = "dark" if isDarkTheme() else "light"
        self.config.theme_mode = new_mode
        rev = {"dark": "深色", "light": "浅色"}
        self.theme_combo.setCurrentText(rev.get(new_mode, "自动"))

    def _open_bilibili_login(self):
        dialog = BilibiliLoginDialog(self.window())
        dialog.login_successful.connect(self._on_bilibili_login_success)
        dialog.exec()

    def _on_bilibili_login_success(self, creds: dict):
        self.bilibili_status.setText("已登录")
        self.bilibili_status.setStyleSheet("color: #27ae60; font-size: 13px;")
        self.bilibili_logout_btn.setVisible(True)
        mw = self.window()
        if hasattr(mw, 'bilibili') and hasattr(mw.bilibili, 'refresh_credential'):
            mw.bilibili.refresh_credential()

    def _clear_bilibili_cookie(self):
        self.cookie_manager.clear_bilibili()
        self.bilibili_status.setText("未登录")
        self.bilibili_status.setStyleSheet("color: #e74c3c; font-size: 13px;")
        self.bilibili_logout_btn.setVisible(False)
        mw = self.window()
        if hasattr(mw, 'bilibili') and hasattr(mw.bilibili, 'refresh_credential'):
            mw.bilibili.refresh_credential()
        InfoBar.success(
            title="已清除", content="Bilibili Cookie 已清除",
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP_RIGHT, duration=3000,
            parent=self.window(),
        )
