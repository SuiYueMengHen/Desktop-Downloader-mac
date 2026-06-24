"""
Login dialog with in-software QR code scanning for Bilibili.
Uses a dedicated QThread with persistent asyncio event loop for login_v2.
"""
import asyncio
from typing import Optional

from PySide6.QtCore import Qt, Signal, QTimer, QThread
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QFrame

from qfluentwidgets import (
    Dialog, PushButton, LineEdit, CaptionLabel,
    InfoBar, InfoBarPosition, FluentIcon as FIF,
    PrimaryPushButton,
)

from app.cookie_manager import CookieManager
from app.utils.helpers import muted_text_color


class BilibiliQrLoginThread(QThread):
    """Dedicated thread with persistent asyncio event loop for Bilibili QR login."""

    qr_ready = Signal(str, object)       # qrcode_key, image_data (PNG bytes)
    login_success = Signal(str, str, str) # sessdata, bili_jct, buvid3
    login_error = Signal(str)
    status_update = Signal(str)           # polling status text

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._qr_obj = None
        self._need_stop = False

    def run(self):
        """Run persistent event loop in this thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def stop(self):
        """Stop the event loop from any thread."""
        self._need_stop = True
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    # ── Public API (thread-safe) ──

    def generate_qr(self):
        """Generate QR code (thread-safe, queues into event loop)."""
        if self._loop and not self._need_stop:
            asyncio.run_coroutine_threadsafe(self._do_generate(), self._loop)

    def poll(self):
        """Poll login status (thread-safe, queues into event loop)."""
        if self._loop and not self._need_stop and self._qr_obj:
            asyncio.run_coroutine_threadsafe(self._do_poll(), self._loop)

    # ── Internal async implementations ──

    async def _do_generate(self):
        try:
            from bilibili_api import login_v2

            self._qr_obj = login_v2.QrCodeLogin(platform=login_v2.QrCodeLoginChannel.WEB)
            await self._qr_obj.generate_qrcode()

            pic = self._qr_obj.get_qrcode_picture()
            # pic is bilibili_api Picture object with .content (raw bytes)
            self.qr_ready.emit("", pic.content)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.login_error.emit(f"生成二维码失败: {str(e)[:80]}")

    async def _do_poll(self):
        try:
            from bilibili_api import login_v2

            state = await self._qr_obj.check_state()

            if state == login_v2.QrCodeLoginEvents.DONE:
                cred = self._qr_obj.get_credential()
                cookies = cred.get_cookies()
                sessdata = cookies.get("SESSDATA", "")
                bili_jct = cookies.get("bili_jct", "")
                buvid3 = cookies.get("buvid3", cookies.get("buvid4", ""))
                self.login_success.emit(sessdata, bili_jct, buvid3)
            elif state == login_v2.QrCodeLoginEvents.SCAN:
                self.status_update.emit("已扫码，请在手机上确认登录...")
            elif state == login_v2.QrCodeLoginEvents.TIMEOUT:
                self.status_update.emit("二维码已过期，请重新生成")
            else:  # CONF (waiting for scan)
                self.status_update.emit("请使用 Bilibili App 扫码...")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.status_update.emit(f"轮询异常: {str(e)[:50]}")


class BilibiliLoginDialog(Dialog):
    """Dialog for Bilibili login via QR code or manual cookie input."""

    login_successful = Signal(dict)

    def __init__(self, parent=None):
        super().__init__("Bilibili 登录", "", parent)
        self.cookie_manager = CookieManager()
        self._poll_timer = QTimer(self)
        self._polling_active = False

        # Start the dedicated QR login thread
        self._qr_thread = BilibiliQrLoginThread(self)
        self._qr_thread.qr_ready.connect(self._on_qr_ready)
        self._qr_thread.login_success.connect(self._on_login_success)
        self._qr_thread.login_error.connect(self._on_login_error)
        self._qr_thread.status_update.connect(self._on_status_update)
        self._qr_thread.start()

        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")

        self._setup_ui()
        self._connect_signals()
        self._load_existing()

        self.setMinimumWidth(500)
        self.setMaximumWidth(550)

    # (the rest of _setup_ui, _connect_signals, etc. remains the same as previous version)

    def _setup_ui(self):
        self.contentLabel.hide()

        self.tabWidget = QFrame(self)
        self.tabLayout = QVBoxLayout(self.tabWidget)
        self.tabLayout.setSpacing(12)

        # ── QR Code Section ──
        self.qr_label = CaptionLabel("扫码登录 (推荐)")
        self.qr_label.setStyleSheet("font-size: 16px; font-weight: bold;")

        self.qr_image_label = QFrame()
        self.qr_image_label.setFixedSize(260, 260)
        self.qr_image_label.setStyleSheet(
            "background-color: white; border-radius: 8px;"
        )
        self.qr_image_layout = QVBoxLayout(self.qr_image_label)
        self.qr_pixmap_label = CaptionLabel("点击下方按钮生成二维码")
        self.qr_pixmap_label.setAlignment(Qt.AlignCenter)
        self.qr_image_layout.addWidget(self.qr_pixmap_label)

        self.qr_status = CaptionLabel("")
        self.qr_status.setAlignment(Qt.AlignCenter)
        self.qr_status.setStyleSheet(f"color: {muted_text_color()};")

        qr_btn_layout = QHBoxLayout()
        self.qr_gen_btn = PrimaryPushButton(FIF.QRCODE, "生成二维码")
        self.qr_refresh_btn = PushButton(FIF.SYNC, "刷新")
        qr_btn_layout.addStretch()
        qr_btn_layout.addWidget(self.qr_gen_btn)
        qr_btn_layout.addWidget(self.qr_refresh_btn)
        qr_btn_layout.addStretch()

        self.tabLayout.addWidget(self.qr_label)
        self.tabLayout.addWidget(self.qr_image_label, 0, Qt.AlignCenter)
        self.tabLayout.addWidget(self.qr_status)
        self.tabLayout.addLayout(qr_btn_layout)

        # ── Separator ──
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #ddd;")
        self.tabLayout.addWidget(sep)

        # ── Manual Cookie Section ──
        manual_label = CaptionLabel("手动填写 Cookie")
        manual_label.setStyleSheet("font-size: 16px; font-weight: bold;")

        self.sessdata_input = LineEdit()
        self.sessdata_input.setPlaceholderText("SESSDATA (必填)")
        self.sessdata_input.setClearButtonEnabled(True)

        self.bili_jct_input = LineEdit()
        self.bili_jct_input.setPlaceholderText("bili_jct (必填)")
        self.bili_jct_input.setClearButtonEnabled(True)

        self.buvid3_input = LineEdit()
        self.buvid3_input.setPlaceholderText("buvid3 (可选)")
        self.buvid3_input.setClearButtonEnabled(True)

        self.save_btn = PrimaryPushButton(FIF.SAVE, "保存 Cookie")

        self.tabLayout.addWidget(manual_label)
        self.tabLayout.addWidget(self.sessdata_input)
        self.tabLayout.addWidget(self.bili_jct_input)
        self.tabLayout.addWidget(self.buvid3_input)
        self.tabLayout.addSpacing(8)
        self.tabLayout.addWidget(self.save_btn, 0, Qt.AlignCenter)

        # Insert into dialog layout
        self.vBoxLayout.insertWidget(0, self.tabWidget)

    def _connect_signals(self):
        self.qr_gen_btn.clicked.connect(self._generate_qr)
        self.qr_refresh_btn.clicked.connect(self._generate_qr)
        self._poll_timer.timeout.connect(self._poll_status)
        self.save_btn.clicked.connect(self._save_manual)

    def _load_existing(self):
        sess = self.cookie_manager.bilibili_sessdata
        jct = self.cookie_manager.bilibili_bili_jct
        buvid = self.cookie_manager.bilibili_buvid3
        if sess:
            self.sessdata_input.setText(sess)
        if jct:
            self.bili_jct_input.setText(jct)
        if buvid:
            self.buvid3_input.setText(buvid)
        if sess and jct:
            self.save_btn.setText("更新 Cookie")
            self.qr_status.setText("已登录 (Cookie 已保存)")

    # ── QR Code Login ──

    def _generate_qr(self):
        self.qr_gen_btn.setEnabled(False)
        self.qr_refresh_btn.setEnabled(False)
        self.qr_pixmap_label.setText("正在获取二维码...")
        self.qr_status.setText("")
        self._polling_active = False
        self._poll_timer.stop()

        # Queue QR generation in the dedicated thread
        self._qr_thread.generate_qr()

    def _on_qr_ready(self, qrcode_key: str, image_data: bytes):
        # Display QR image
        pixmap = QPixmap()
        pixmap.loadFromData(image_data, "PNG")
        scaled = pixmap.scaled(240, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.qr_pixmap_label.setPixmap(scaled)
        self.qr_pixmap_label.setText("")

        self.qr_status.setText("请使用 Bilibili App 扫码登录")
        self.qr_gen_btn.setEnabled(True)
        self.qr_refresh_btn.setEnabled(True)

        # Start polling
        self._polling_active = True
        self._poll_timer.start(2000)

    def _poll_status(self):
        if not self._polling_active:
            self._poll_timer.stop()
            return
        self._qr_thread.poll()

    def _on_login_success(self, sessdata: str, bili_jct: str, buvid3: str):
        self._polling_active = False
        self._poll_timer.stop()

        if sessdata and bili_jct:
            self.cookie_manager.bilibili_sessdata = sessdata
            self.cookie_manager.bilibili_bili_jct = bili_jct
            self.cookie_manager.bilibili_buvid3 = buvid3

            creds = {"sessdata": sessdata, "bili_jct": bili_jct, "buvid3": buvid3}
            self.login_successful.emit(creds)

            InfoBar.success(
                title="登录成功", content="Bilibili Cookie 已保存",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=3000, parent=self,
            )
            self.accept()
        else:
            self.qr_status.setText("登录成功但 Cookie 数据不完整")

    def _on_status_update(self, msg: str):
        """Handle status update from QR thread."""
        self.qr_status.setText(msg)
        # If QR expired, reset UI
        if "过期" in msg:
            self._polling_active = False
            self._poll_timer.stop()
            self.qr_pixmap_label.setText("二维码已过期")
            self.qr_gen_btn.setEnabled(True)
            self.qr_refresh_btn.setEnabled(True)

    def _on_login_error(self, msg: str):
        self.qr_pixmap_label.setText("生成失败")
        self.qr_status.setText(msg)
        self.qr_gen_btn.setEnabled(True)
        self.qr_refresh_btn.setEnabled(True)
        self._polling_active = False

    # ── Manual Cookie ──

    def _save_manual(self):
        sessdata = self.sessdata_input.text().strip()
        bili_jct = self.bili_jct_input.text().strip()
        buvid3 = self.buvid3_input.text().strip()

        if not sessdata or not bili_jct:
            InfoBar.error(
                title="输入不完整", content="SESSDATA 和 bili_jct 为必填项",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=3000, parent=self,
            )
            return

        self.cookie_manager.bilibili_sessdata = sessdata
        self.cookie_manager.bilibili_bili_jct = bili_jct
        self.cookie_manager.bilibili_buvid3 = buvid3

        self.login_successful.emit({"sessdata": sessdata, "bili_jct": bili_jct, "buvid3": buvid3})

        InfoBar.success(
            title="保存成功", content="Bilibili Cookie 已保存",
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP_RIGHT, duration=3000, parent=self,
        )
        self.accept()

    def closeEvent(self, event):
        self._polling_active = False
        self._poll_timer.stop()
        self._qr_thread.stop()
        if not self._qr_thread.wait(3000):
            self._qr_thread.terminate()
            self._qr_thread.wait()
        super().closeEvent(event)
