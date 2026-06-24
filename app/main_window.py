"""
Main application window with FluentWindow sidebar navigation.
"""
import sys
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QCloseEvent

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
from app.clipboard_monitor import ClipboardMonitor
from app.notification import NotificationService
from app.platforms.bilibili import BilibiliPlatform
from app.utils.helpers import detect_url_type


class MainWindow(FluentWindow):
    """Main window with Fluent Design sidebar navigation."""

    def __init__(self):
        super().__init__()

        self.config = Config()
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

        self._batch_urls: list[str] = []
        self._batch_index: int = 0

        # Create pages - set unique object names for navigation routing
        self.home_page = HomePage(self)
        self.home_page.setObjectName("homePage")

        self.download_page = DownloadPage(self)
        self.download_page.setObjectName("downloadPage")

        self.settings_page = SettingsPage(self)
        self.settings_page.setObjectName("settingsPage")

        self.history_page = HistoryPage(self)
        self.history_page.setObjectName("historyPage")

        self.up_page = UpPage(self)
        self.up_page.setObjectName("upPage")

        self.collection_page = CollectionPage(self)
        self.collection_page.setObjectName("collectionPage")

        self.search_page = SearchPage(self)
        self.search_page.setObjectName("searchPage")

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

        # Initial credential check after 5 seconds (let UI settle)
        QTimer.singleShot(5000, self._refresh_bilibili_credential)

    def _init_navigation(self):
        """Set up sidebar navigation items."""
        self.addSubInterface(self.home_page, FIF.DOWNLOAD, "下载")
        self.addSubInterface(self.download_page, FIF.PLAY, "下载列表")
        self.addSubInterface(self.history_page, FIF.HISTORY, "下载历史")
        self.addSubInterface(self.up_page, FIF.PEOPLE, "UP主空间")
        self.addSubInterface(self.collection_page, FIF.ALBUM, "UP主合集")
        self.addSubInterface(self.search_page, FIF.SEARCH, "搜索")

        self.navigationInterface.addSeparator()

        self.addSubInterface(
            self.settings_page, FIF.SETTING, "设置",
            position=NavigationItemPosition.BOTTOM,
        )

    def _on_theme_toggle(self):
        """Toggle theme from navigation button."""
        toggleTheme()
        new_mode = "dark" if isDarkTheme() else "light"
        self.config.theme_mode = new_mode
        # Sync settings page combo if available
        if hasattr(self.settings_page, 'theme_combo'):
            theme_map_rev = {"dark": "深色", "light": "浅色"}
            self.settings_page.theme_combo.setCurrentText(theme_map_rev.get(new_mode, "自动"))

    def _init_window(self):
        """Configure window properties."""
        self.resize(1100, 750)
        self.setMinimumSize(800, 550)
        self.setWindowTitle("Desktop Downloader - 多平台视频下载器")
        self._update_window_icon()
        qconfig.themeChanged.connect(self._update_window_icon)

    def _update_window_icon(self):
        self.setWindowIcon(FIF.DOWNLOAD.icon())

    def _init_shortcuts(self):
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

    def _focus_url_input(self):
        """Switch to home page and focus the URL input."""
        self.switchTo(self.home_page)
        self.home_page.url_input.setFocus()
        self.home_page.url_input.selectAll()

    def _trigger_url_parse(self):
        """If on home page, trigger URL parsing."""
        if self.stackedWidget.currentWidget() == self.home_page:
            self.home_page._on_parse_url()

    def _on_escape(self):
        """Handle Escape key — cancel batch mode or go home."""
        if self.home_page._in_batch_mode:
            self.home_page._exit_batch_mode()
        elif self.stackedWidget.currentWidget() != self.home_page:
            self.switchTo(self.home_page)

    def _focus_search(self):
        """Switch to search page and focus the search input."""
        self.switchTo(self.search_page)
        self.search_page.focus_search()

    def _connect_signals(self):
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
        self.download_manager.on_completed(lambda p: self.history_page.refresh())

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

        # Settings page tray toggle
        if hasattr(self.settings_page, 'tray_toggled'):
            self.settings_page.tray_toggled.connect(self._on_tray_toggled)

        # Settings page schedule changed
        if hasattr(self.settings_page, 'schedule_changed'):
            self.settings_page.schedule_changed.connect(
                self.download_manager.on_schedule_changed
            )

        # UP主 space -> parse video and jump to home page
        self.up_page.parse_video.connect(self._on_up_parse_video)

        # Search page -> parse video and jump to home page
        self.search_page.parse_video.connect(self._on_up_parse_video)
        # Search page -> view uploader -> jump to up_page
        self.search_page.view_uploader.connect(self._on_view_uploader)

        # Collection page -> batch parse
        self.collection_page.parse_batch_requested.connect(self._on_collection_parse_batch)

        self.home_page.resolve_complete.connect(self._on_batch_resolve_complete)
        self.home_page.parse_complete.connect(self._on_batch_parse_complete)
        self.home_page.batch_cancelled.connect(self._cancel_batch)

    def _apply_theme(self):
        """Apply saved theme mode."""
        mode = self.config.theme_mode
        if mode == "dark":
            setTheme(Theme.DARK)
        elif mode == "light":
            setTheme(Theme.LIGHT)
        # "auto" = default (system)

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

    def _on_clipboard_url(self, url: str):
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

    def _on_up_parse_video(self, url: str):
        """Handle parse request from UP主 space or search page."""
        self.request_parse(url, source="up_or_search")

    def _on_view_uploader(self, uid: int):
        """Jump to UP主 space page from search results."""
        url = f"https://space.bilibili.com/{uid}"
        self.switchTo(self.up_page)
        self.up_page.url_input.setText(url)
        self.up_page._on_load_up()

    def _on_batch_urls(self, urls: list[str]):
        """Handle batch import from the batch import dialog."""
        # Guard: exit existing batch mode first
        if self.home_page._in_batch_mode:
            self.home_page._exit_batch_mode()
        self._batch_urls = urls
        self._batch_index = 0
        QTimer.singleShot(200, self._submit_next_batch_url)

    def _on_collection_parse_batch(self, urls: list[str]):
        """Handle batch parse request from collection page."""
        # Guard: exit existing batch mode first
        if self.home_page._in_batch_mode:
            self.home_page._exit_batch_mode()
        self._batch_urls = urls
        self._batch_index = 0
        self.home_page.enter_batch_mode()
        self.switchTo(self.home_page)
        self._submit_next_batch_url()

    def _submit_next_batch_url(self):
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

    def _on_batch_parse_complete(self):
        if self._batch_urls:
            QTimer.singleShot(1500, self._submit_next_batch_url)

    def _cancel_batch(self):
        self._batch_urls = []
        self._batch_index = 0

    def _refresh_bilibili_credential(self):
        """Periodically refresh Bilibili credentials and check validity.

        Reloads cookies from config (in case user updated them in settings),
        rebuilds the credential, and validates it with a lightweight API call.
        If the credential is expired, shows a warning notification.
        """
        import asyncio
        was_logged_in = self.bilibili._check_login()

        # Reload cookies from config and rebuild credential
        self.bilibili.refresh_credential()

        # Propagate refreshed credential to all pages
        for page in (self.up_page, self.collection_page, self.search_page):
            if hasattr(page, '_platform') and page._platform is self.bilibili:
                page._platform = self.bilibili  # same instance, already refreshed

        if not self.bilibili._check_login():
            if was_logged_in:
                # Was logged in but now credentials are gone
                InfoBar.warning(
                    title="B站登录已失效",
                    content="Bilibili 登录凭证已失效，请重新登录",
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT, duration=5000,
                    parent=self,
                )
            return

        # Validate credential with API call (async, run in background)
        try:
            loop = asyncio.new_event_loop()
            try:
                is_valid = loop.run_until_complete(
                    self.bilibili.validate_credential()
                )
                if not is_valid and was_logged_in:
                    InfoBar.warning(
                        title="B站登录已失效",
                        content="Bilibili 登录已过期，请前往设置重新登录",
                        orient=Qt.Horizontal, isClosable=True,
                        position=InfoBarPosition.TOP_RIGHT, duration=5000,
                        parent=self,
                    )
                    print("[INFO] Bilibili credential validation: expired",
                          file=sys.stderr, flush=True)
                else:
                    print("[INFO] Bilibili credential validation: OK",
                          file=sys.stderr, flush=True)
            finally:
                loop.close()
        except Exception as e:
            print(f"[WARNING] Credential validation error: {e}",
                  file=sys.stderr, flush=True)

    def _on_batch_resolve_complete(self):
        pass  # kept for compatibility

    def switchTo(self, widget):
        """Switch to a specific page with lifecycle management.

        Calls on_page_left() on the current page before switching to
        cancel in-flight workers and free resources. The target page's
        results remain visible when the user navigates back.
        """
        current = self.stackedWidget.currentWidget()
        if current is not widget and hasattr(current, 'on_page_left'):
            try:
                current.on_page_left()
            except Exception:
                pass  # lifecycle errors must not block navigation
        self.stackedWidget.setCurrentWidget(widget)
        # Sync the navigation sidebar highlight with the current page
        nav = self.navigationInterface
        route_key = widget.objectName()
        if route_key and hasattr(nav, 'setCurrentItem'):
            nav.setCurrentItem(route_key)

    def _toggle_visibility(self):
        """Toggle window visibility (show/hide from tray)."""
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def _quit_app(self):
        """Force quit the application from tray menu."""
        self.config.flush()
        QApplication.quit()

    def _on_tray_toggled(self, enabled: bool):
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

    def _do_cleanup(self):
        """Shared cleanup logic."""
        self.clipboard_monitor.stop()
        self.themeListener.requestInterruption()
        self.themeListener.wait(3000)
        self.themeListener.deleteLater()
        self.download_manager.stop()
        self.config.flush()
