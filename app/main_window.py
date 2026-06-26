"""
Main application window with FluentWindow sidebar navigation.
"""
import asyncio
import logging
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QKeySequence, QShortcut, QCloseEvent

logger = logging.getLogger(__name__)

from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, FluentIcon as FIF,
    InfoBar, InfoBarPosition, Theme, setTheme, toggleTheme, isDarkTheme,
    SystemThemeListener, qconfig,
)

from app.config import Config
from app.download_manager import DownloadManager
from app.cookie_manager import CookieManager
from app.ui.home_page import HomePage
from app.ui.download_page import DownloadPage
from app.ui.settings_page import SettingsPage
from app.ui.history_page import HistoryPage
from app.ui.up_page import UpPage
from app.ui.collection_page import CollectionPage
from app.ui.search_page import SearchPage
from app.ui.splash_screen import SplashOverlay
from app.clipboard_monitor import ClipboardMonitor
from app.notification import NotificationService
from app.update_checker import UpdateChecker
from app.platforms.bilibili import BilibiliPlatform
from app.utils.helpers import detect_url_type
from typing import Optional


class CredentialCheckWorker(QThread):
    """Validates Bilibili credential in a background thread."""
    result_ready = Signal(bool, bool)  # is_valid, was_logged_in

    def __init__(self, bilibili, was_logged_in: bool):
        super().__init__()
        self.bilibili = bilibili
        self.was_logged_in = was_logged_in

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            try:
                is_valid = loop.run_until_complete(
                    self.bilibili.validate_credential()
                )
            finally:
                loop.close()
        except Exception:
            is_valid = False
        self.result_ready.emit(is_valid, self.was_logged_in)


class MainWindow(FluentWindow):
    """Main window with Fluent Design sidebar navigation."""

    def __init__(self, was_crashed: bool = False):
        super().__init__()

        self.config = Config()

        if was_crashed:
            from qfluentwidgets import InfoBar, InfoBarPosition
            logging.warning("App recovered from previous crash")
            QTimer.singleShot(3000, lambda: InfoBar.warning(
                title="上次异常退出",
                content="应用上次未正常关闭，日志已保存至 ~/.desktop-downloader/app.log",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=10000,
                parent=self,
            ))
        self.cookie_manager = CookieManager()
        self.download_manager = DownloadManager(
            mc=self.config.max_concurrent_downloads
        )

        # Platform instances
        self.bilibili = BilibiliPlatform()

        # Clipboard monitor
        self.clipboard_monitor = ClipboardMonitor(self)
        self.clipboard_monitor.url_detected.connect(self._on_clipboard_url)

        # Notification service (system tray + sound)
        self.notification_service = NotificationService(self)

        # Update checker (background)
        self.update_checker = UpdateChecker(parent=self)
        self.update_checker.update_available.connect(self._on_update_available)
        QTimer.singleShot(5000, self._check_updates)

        self._batch_urls: list[str] = []
        self._batch_index: int = 0
        self._cred_worker: Optional[CredentialCheckWorker] = None

        # Set window size BEFORE showing — prevents small-then-big resize
        # which would make the splash overlay's parent.rect() incorrect
        self.resize(1100, 750)
        self.setMinimumSize(800, 550)

        # Show window first so splash overlay positions correctly on screen
        self.show()
        QApplication.processEvents()

        # Show splash overlay to cover initialization work
        self.splash = None
        if self.config.startup_animation:
            self.splash = SplashOverlay(self)
            self.splash.raise_()
            self.splash.show()
            QApplication.processEvents()

        # Lazy page loading — only HomePage created eagerly (always shown first)
        self._pages: dict[str, QWidget] = {}
        self.home_page = HomePage(self)
        self.home_page.setObjectName("homePage")
        self._pages["homePage"] = self.home_page

        # Init UI
        self._init_navigation()
        self._init_window()
        self._init_shortcuts()
        self._connect_signals()

        # Disable page switch animation for instant navigation
        if hasattr(self, 'stackedWidget'):
            self.stackedWidget.setAnimationEnabled(False)

        # Apply theme
        self._apply_theme()

        # Listen for system theme changes (when in AUTO mode)
        self.themeListener = SystemThemeListener(self)
        self.themeListener.start()

        # Auto-start clipboard monitor if enabled in config
        if self.config.clipboard_monitor_enabled:
            self.clipboard_monitor.start()

        # Periodic credential refresh timer (every 30 minutes)
        # Reloads cookies from config and validates login status
        self._cred_refresh_timer = QTimer(self)
        self._cred_refresh_timer.setInterval(30 * 60 * 1000)  # 30 min
        self._cred_refresh_timer.timeout.connect(self._refresh_bilibili_credential)
        self._cred_refresh_timer.start()

        # Initial credential check after splash is done and UI settles
        QTimer.singleShot(
            3000 if self.splash else 5000,
            self._refresh_bilibili_credential,
        )

        # Dismiss splash after a brief delay so the user can see the animation
        if self.splash:
            QTimer.singleShot(1000, self._dismiss_splash)

    def _dismiss_splash(self) -> None:
        self.splash.set_status("加载完成")
        self.splash.dismiss()
        self.splash = None

    def _check_updates(self) -> None:
        self.update_checker.check()

    def _on_update_available(self, version: str, url: str) -> None:
        InfoBar.success(
            title="发现新版本",
            content=f"Desktop Downloader {version} 已可用{' · 点击下载' if url else ''}",
            orient=Qt.Horizontal, isClosable=True,
            position=InfoBarPosition.TOP_RIGHT, duration=15000,
            parent=self,
        )

    @property
    def download_page(self) -> DownloadPage:
        return self._get_page("downloadPage")

    @property
    def settings_page(self) -> SettingsPage:
        return self._get_page("settingsPage")

    @property
    def history_page(self) -> HistoryPage:
        return self._get_page("historyPage")

    @property
    def up_page(self) -> UpPage:
        return self._get_page("upPage")

    @property
    def collection_page(self) -> CollectionPage:
        return self._get_page("collectionPage")

    @property
    def search_page(self) -> SearchPage:
        return self._get_page("searchPage")

    def _get_page(self, name: str) -> QWidget:
        """Get or create a lazily-initialized page."""
        if name not in self._pages:
            cls = {
                "downloadPage": DownloadPage,
                "settingsPage": SettingsPage,
                "historyPage": HistoryPage,
                "upPage": UpPage,
                "collectionPage": CollectionPage,
                "searchPage": SearchPage,
            }[name]
            page = cls(self)
            page.setObjectName(name)
            self._pages[name] = page
        return self._pages[name]

    def _init_navigation(self) -> None:
        """Set up sidebar navigation items."""
        self.addSubInterface(self.home_page, FIF.DOWNLOAD, "下载")
        self.addSubInterface(self._get_page("downloadPage"), FIF.PLAY, "下载列表")
        self.addSubInterface(self._get_page("historyPage"), FIF.HISTORY, "下载历史")
        self.addSubInterface(self._get_page("upPage"), FIF.PEOPLE, "UP主空间")
        self.addSubInterface(self._get_page("collectionPage"), FIF.ALBUM, "UP主合集")
        self.addSubInterface(self._get_page("searchPage"), FIF.SEARCH, "搜索")

        self.navigationInterface.addSeparator()

        self.addSubInterface(
            self._get_page("settingsPage"), FIF.SETTING, "设置",
            position=NavigationItemPosition.BOTTOM,
        )

    def _on_theme_toggle(self) -> None:
        """Toggle theme from navigation button."""
        toggleTheme()
        new_mode = "dark" if isDarkTheme() else "light"
        self.config.theme_mode = new_mode
        # Sync settings page combo if available
        if hasattr(self.settings_page, 'theme_combo'):
            theme_map_rev = {"dark": "深色", "light": "浅色"}
            self.settings_page.theme_combo.setCurrentText(theme_map_rev.get(new_mode, "自动"))

    def _init_window(self) -> None:
        """Configure window properties."""
        self.resize(1100, 750)
        self.setMinimumSize(800, 550)
        self.setWindowTitle("Desktop Downloader - 多平台视频下载器")
        self._update_window_icon()
        qconfig.themeChanged.connect(self._update_window_icon)

    def _update_window_icon(self) -> None:
        self.setWindowIcon(FIF.DOWNLOAD.icon())

    def _init_shortcuts(self) -> None:
        """Register global keyboard shortcuts."""
        # Ctrl+L / Ctrl+Shift+V — Focus URL input on home page
        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(
            lambda: self._focus_url_input()
        )
        QShortcut(QKeySequence("Ctrl+Shift+V"), self).activated.connect(
            lambda: self._focus_url_input()
        )

        # Ctrl+D — Switch to download page
        QShortcut(QKeySequence("Ctrl+D"), self).activated.connect(
            lambda: self.switchTo(self.download_page)
        )

        # Ctrl+Shift+H — Switch to history page
        QShortcut(QKeySequence("Ctrl+Shift+H"), self).activated.connect(
            lambda: self.switchTo(self.history_page)
        )

        # Ctrl+, — Open settings
        QShortcut(QKeySequence("Ctrl+,"), self).activated.connect(
            lambda: self.switchTo(self.settings_page)
        )

        # Ctrl+Q — Quit app
        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(
            lambda: QApplication.quit()
        )

        # Ctrl+Enter — Trigger parse on current URL
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(
            self._trigger_url_parse
        )

        # Ctrl+F — Focus search input on search page
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(
            lambda: self._focus_search()
        )

        # Escape — If in batch mode on home page, cancel; otherwise go home
        QShortcut(QKeySequence("Escape"), self).activated.connect(
            self._on_escape
        )

    def _focus_url_input(self) -> None:
        """Switch to home page and focus the URL input."""
        self.switchTo(self.home_page)
        self.home_page.url_input.setFocus()
        self.home_page.url_input.selectAll()

    def _trigger_url_parse(self) -> None:
        """If on home page, trigger URL parsing."""
        if self.stackedWidget.currentWidget() == self.home_page:
            self.home_page._on_parse_url()

    def _on_escape(self) -> None:
        """Handle Escape key — cancel batch mode or go home."""
        if self.home_page._in_batch_mode:
            self.home_page._exit_batch_mode()
        elif self.stackedWidget.currentWidget() != self.home_page:
            self.switchTo(self.home_page)

    def _focus_search(self) -> None:
        """Switch to search page and focus the search input."""
        self.switchTo(self.search_page)
        self.search_page.focus_search()

    def _connect_signals(self) -> None:
        """Connect internal signals."""
        # Update download manager max concurrent when settings change
        if hasattr(self.settings_page, 'concurrent_changed'):
            self.settings_page.concurrent_changed.connect(
                lambda v: setattr(self.download_manager, 'max_concurrent', v)
            )
        # Live speed limit update — propagates to running download workers
        if hasattr(self.settings_page, 'speed_limit_changed'):
            self.settings_page.speed_limit_changed.connect(
                lambda v: setattr(self.download_manager, 'speed_limit', v)
            )
        # Live transcode mode update — propagates to running download workers
        if hasattr(self.settings_page, 'transcode_changed'):
            self.settings_page.transcode_changed.connect(
                lambda v: setattr(self.download_manager, 'transcode_mode', v)
            )

        # Platform events from home page
        self.home_page.download_requested.connect(self._on_download_requested)

        # Download manager signals to download page
        self.download_manager.on_progress(self.download_page.update_progress)
        self.download_manager.on_completed(self.download_page.on_download_completed)
        self.download_manager.on_error(self.download_page.on_download_error)
        self.download_manager.task_added.connect(self.download_page.on_task_added)

        # Refresh history page when download completes
        self.download_manager.on_completed(lambda p: self.history_page.append_entry())

        # Notification service for download events
        self.download_manager.on_completed(
            lambda p: self.notification_service.notify_complete(
                "下载完成", f"{p.filename} 下载完成"
            )
        )
        self.download_manager.on_error(
            lambda p: self.notification_service.notify_error(
                "下载失败", f"{p.filename}: {p.error_msg[:80]}"
            )
        )

        # System tray signals
        self.notification_service.show_window_requested.connect(self._toggle_visibility)
        self.notification_service.quit_requested.connect(self._quit_app)

        # Click notification → show window + switch to download page
        self.notification_service.notification_clicked.connect(
            lambda _: self.switchTo(self.download_page) if self.isMinimized() or not self.isVisible() else None
        )
        self.notification_service.notification_clicked.connect(
            lambda _: self._toggle_visibility() if self.isMinimized() or not self.isVisible() else None
        )

        # Settings page tray toggle
        if hasattr(self.settings_page, 'tray_toggled'):
            self.settings_page.tray_toggled.connect(self._on_tray_toggled)

        # Settings page schedule changed
        if hasattr(self.settings_page, 'schedule_changed'):
            self.settings_page.schedule_changed.connect(
                self.download_manager.on_schedule_changed
            )

        # Schedule window state change notification
        self.download_manager.schedule_state_changed.connect(
            lambda in_window: self.notification_service.notify_complete(
                "下载调度", "已进入下载时段，开始下载" if in_window else "已离开下载时段，暂停下载"
            )
        )

        # UP主 space -> parse video and jump to home page
        self.up_page.parse_video.connect(self._on_up_parse_video)

        # Search page -> parse video and jump to home page
        self.search_page.parse_video.connect(self._on_up_parse_video)
        # Search page -> view uploader -> jump to up_page
        self.search_page.view_uploader.connect(self._on_view_uploader)

        # Collection page -> batch parse
        self.collection_page.parse_batch_requested.connect(self._on_collection_parse_batch)

        self.home_page.parse_complete.connect(self._on_batch_parse_complete)
        self.home_page.batch_cancelled.connect(self._cancel_batch)

    def _apply_theme(self) -> None:
        """Apply saved theme mode."""
        mode = self.config.theme_mode
        if mode == "dark":
            setTheme(Theme.DARK)
        elif mode == "light":
            setTheme(Theme.LIGHT)
        if self.splash:
            self.splash.refresh_theme()

    def _on_download_requested(self, task):
        """Handle a new download request from home page."""
        task_id = self.download_manager.add_task(task)
        InfoBar.success(
            title="已添加下载",
            content=f"{task.video_info.title[:30]}... 已加入下载队列",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=3000,
            parent=self,
        )
        # Only switch to download page if not in batch mode
        if not self.home_page._in_batch_mode:
            self.switchTo(self.download_page)
        return task_id

    def _on_clipboard_url(self, url: str) -> None:
        """Handle a URL detected from clipboard monitor."""
        self.request_parse(url, source="clipboard")

    def request_parse(self, url: str, source: str = ""):
        """Central entry point for all URL parse requests.

        Routes the URL to the appropriate page based on its type.
        Guards against starting new operations during active batch mode.

        Args:
            url: The URL to parse.
            source: Where the request came from (for logging/debugging).
        """
        # Guard: don't start new parse during batch mode
        if self.home_page._in_batch_mode:
            InfoBar.warning(
                title="批量解析进行中",
                content="请等待当前批量解析完成，或按 Esc 取消",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=3000,
                parent=self,
            )
            return

        url_type = detect_url_type(url)

        if url_type == "collection":
            if self.collection_page.load_url(url):
                self.switchTo(self.collection_page)
                InfoBar.info(
                    title="检测到UP主合集", content="已自动跳转至合集页",
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT, duration=3000,
                    parent=self,
                )
            else:
                InfoBar.warning(
                    title="解析失败", content="无法解析合集ID",
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT, duration=3000,
                    parent=self,
                )
        elif url_type == "space":
            if self.up_page.load_url(url):
                self.switchTo(self.up_page)
                InfoBar.info(
                    title="检测到UP主空间", content="已自动跳转至UP主空间页",
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT, duration=3000,
                    parent=self,
                )
            else:
                InfoBar.warning(
                    title="解析失败", content="无法识别UP主UID",
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT, duration=3000,
                    parent=self,
                )
        else:
            self.switchTo(self.home_page)
            self.home_page.url_input.setText(url)
            self.home_page._on_parse_url()
            if source == "clipboard":
                InfoBar.info(
                    title="检测到链接", content="已自动开始解析剪贴板中的视频链接",
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT, duration=3000,
                    parent=self,
                )

    def _on_up_parse_video(self, url: str) -> None:
        """Handle parse request from UP主 space or search page."""
        self.request_parse(url, source="up_or_search")

    def _on_view_uploader(self, uid: int) -> None:
        """Jump to UP主 space page from search results."""
        url = f"https://space.bilibili.com/{uid}"
        self.switchTo(self.up_page)
        self.up_page.url_input.setText(url)
        self.up_page._on_load_up()

    def _on_batch_urls(self, urls: list[str]) -> None:
        """Handle batch import from the batch import dialog."""
        # Guard: exit existing batch mode first
        if self.home_page._in_batch_mode:
            self.home_page._exit_batch_mode()
        self._batch_urls = urls
        self._batch_index = 0
        QTimer.singleShot(200, self._submit_next_batch_url)

    def _on_collection_parse_batch(self, urls: list[str]) -> None:
        """Handle batch parse request from collection page."""
        # Guard: exit existing batch mode first
        if self.home_page._in_batch_mode:
            self.home_page._exit_batch_mode()
        self._batch_urls = urls
        self._batch_index = 0
        self.home_page.enter_batch_mode()
        self.switchTo(self.home_page)
        self._submit_next_batch_url()

    def _submit_next_batch_url(self) -> None:
        if self._batch_index >= len(self._batch_urls):
            self._batch_urls = []
            self._batch_index = 0
            # Reset batch mode flag so request_parse() works again
            self.home_page._finish_batch_mode()
            InfoBar.success(
                title="批量解析完成",
                content="所有视频已解析完毕，可在下方选择画质后分别下载",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=5000,
                parent=self,
            )
            return

        url = self._batch_urls[self._batch_index]
        self._batch_index += 1

        self.home_page._on_parse_url_batch(url)

    def _on_batch_parse_complete(self) -> None:
        if self._batch_urls:
            QTimer.singleShot(1500, self._submit_next_batch_url)

    def _cancel_batch(self) -> None:
        self._batch_urls = []
        self._batch_index = 0

    def _refresh_bilibili_credential(self) -> None:
        was_logged_in = self.bilibili._check_login()
        self.bilibili.refresh_credential()
        for page in (self.up_page, self.collection_page, self.search_page):
            if hasattr(page, '_platform') and page._platform is self.bilibili:
                page._platform = self.bilibili

        if not self.bilibili._check_login():
            if was_logged_in:
                InfoBar.warning(
                    title="B站登录已失效",
                    content="Bilibili 登录凭证已失效，请重新登录",
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT, duration=5000,
                    parent=self,
                )
            return

        if self._cred_worker and self._cred_worker.isRunning():
            self._cred_worker.requestInterruption()
            self._cred_worker.wait(2000)
        self._cred_worker = CredentialCheckWorker(self.bilibili, was_logged_in)
        self._cred_worker.result_ready.connect(self._on_credential_result)
        self._cred_worker.finished.connect(self._on_cred_worker_finished)
        self._cred_worker.start()

    def _on_credential_result(self, is_valid: bool, was_logged_in: bool) -> None:
        if not is_valid and was_logged_in:
            InfoBar.warning(
                title="B站登录已失效",
                content="Bilibili 登录已过期，请前往设置重新登录",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP_RIGHT, duration=5000,
                parent=self,
            )

    def _on_cred_worker_finished(self) -> None:
        self._cred_worker = None

    def switchTo(self, widget) -> None:
        """Switch to a specific page with lifecycle management.

        Calls on_page_left() on the current page before switching to
        cancel in-flight workers and free resources. The target page's
        results remain visible when the user navigates back.
        """
        # If widget is a route key string, resolve to the actual page instance
        if isinstance(widget, str):
            widget = self._get_page(widget)
        current = self.stackedWidget.currentWidget()
        if current is not widget and hasattr(current, 'on_page_left'):
            try:
                current.on_page_left()
            except Exception:
                logger.warning("on_page_left error during navigation", exc_info=True)
        self.stackedWidget.setCurrentWidget(widget)
        # Sync the navigation sidebar highlight with the current page
        nav = self.navigationInterface
        route_key = widget.objectName()
        if route_key and hasattr(nav, 'setCurrentItem'):
            nav.setCurrentItem(route_key)

    def _toggle_visibility(self) -> None:
        """Toggle window visibility (show/hide from tray)."""
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def _quit_app(self) -> None:
        """Force quit the application from tray menu."""
        self.config.flush()
        QApplication.quit()

    def _on_tray_toggled(self, enabled: bool) -> None:
        """Handle tray enable/disable toggle from settings."""
        self.config.minimize_to_tray = enabled

    def closeEvent(self, event: QCloseEvent):
        """Close or minimize to tray based on config."""
        if self.config.minimize_to_tray:
            event.ignore()
            self.hide()
            self.notification_service.notify_complete(
                "Desktop Downloader",
                "应用已最小化到系统托盘，双击图标恢复窗口"
            )
            return
        self._do_cleanup()
        super().closeEvent(event)

    def _do_cleanup(self) -> None:
        self._cred_refresh_timer.stop()
        if self._cred_worker and self._cred_worker.isRunning():
            self._cred_worker.requestInterruption()
            self._cred_worker.wait(3000)
        self.clipboard_monitor.stop()
        self.themeListener.requestInterruption()
        self.themeListener.wait(3000)
        self.themeListener.deleteLater()
        self.download_manager.stop()
        self.config.flush()
