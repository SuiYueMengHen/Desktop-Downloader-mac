"""
Configuration management for the desktop downloader.
"""
import json
import threading
from pathlib import Path


class Config:
    """Application configuration manager - singleton pattern."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # Config file path
        self._config_dir = Path.home() / ".desktop-downloader"
        self._config_file = self._config_dir / "config.json"
        self._cookie_dir = self._config_dir / "cookies"

        # Default settings
        self._data = {
            "download_path": str(Path.home() / "Downloads" / "DesktopDownloader"),
            "max_concurrent_downloads": 3,
            "download_speed_limit": 0,
            "theme_mode": "auto",
            "language": "zh_CN",
            "bilibili_sessdata": "",
            "bilibili_bili_jct": "",
            "bilibili_buvid3": "",
            "proxy_enabled": False,
            "proxy_url": "",
            "save_metadata": True,
            "clipboard_monitor_enabled": False,
            "notification_enabled": True,
            "notification_sound": True,
            "minimize_to_tray": False,
            "post_download_transcode": "none",
            "schedule_enabled": False,
            "schedule_start": "23:00",
            "schedule_end": "07:00",
            "schedule_days": [0, 1, 2, 3, 4, 5, 6],
        }

        # Debounced save: writes to disk at most once per DEBOUNCE_MS
        self._dirty = False
        self._save_timer: threading.Timer = None
        self._DEBOUNCE_MS = 1.0  # seconds

        self._ensure_dirs()
        self.load()

    def _ensure_dirs(self):
        """Ensure config and cookie directories exist."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._cookie_dir.mkdir(parents=True, exist_ok=True)

    @property
    def config_dir(self) -> Path:
        return self._config_dir

    @property
    def cookie_dir(self) -> Path:
        return self._cookie_dir

    def load(self):
        """Load config from file."""
        if self._config_file.exists():
            try:
                with open(self._config_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self._data.update(saved)
            except (json.JSONDecodeError, IOError):
                pass

    def _do_save(self):
        """Persist config JSON to disk (called by debounce timer or directly)."""
        self._dirty = False
        self._ensure_dirs()
        with open(self._config_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def save(self):
        """Debounced save — delays disk write until 1s after the last change."""
        self._dirty = True
        if self._save_timer and self._save_timer.is_alive():
            self._save_timer.cancel()
        self._save_timer = threading.Timer(self._DEBOUNCE_MS, self._do_save)
        self._save_timer.daemon = True
        self._save_timer.start()

    def flush(self):
        """Force an immediate write, cancelling any pending debounce."""
        if self._save_timer and self._save_timer.is_alive():
            self._save_timer.cancel()
            self._save_timer = None
        if self._dirty:
            self._do_save()

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value):
        self._data[key] = value
        self.save()

    @property
    def download_path(self) -> str:
        return self._data["download_path"]

    @download_path.setter
    def download_path(self, path: str):
        self._data["download_path"] = path
        self.save()

    @property
    def max_concurrent_downloads(self) -> int:
        return self._data["max_concurrent_downloads"]

    @max_concurrent_downloads.setter
    def max_concurrent_downloads(self, value: int):
        self._data["max_concurrent_downloads"] = max(1, min(10, value))
        self.save()

    @property
    def theme_mode(self) -> str:
        return self._data["theme_mode"]

    @theme_mode.setter
    def theme_mode(self, value: str):
        self._data["theme_mode"] = value
        self.save()

    @property
    def proxy_enabled(self) -> bool:
        return self._data.get("proxy_enabled", False)

    @proxy_enabled.setter
    def proxy_enabled(self, value: bool):
        self._data["proxy_enabled"] = value
        self.save()

    @property
    def proxy_url(self) -> str:
        return self._data.get("proxy_url", "")

    @proxy_url.setter
    def proxy_url(self, value: str):
        self._data["proxy_url"] = value
        self.save()

    @property
    def download_speed_limit(self) -> int:
        """Download speed limit in KB/s per concurrent download. 0 = unlimited."""
        return self._data.get("download_speed_limit", 0)

    @download_speed_limit.setter
    def download_speed_limit(self, value: int):
        self._data["download_speed_limit"] = max(0, value)
        self.save()

    @property
    def ffmpeg_location(self) -> str:
        """Return the bundled ffmpeg path (macOS or Windows).
        Result is cached after the first call since the binary location
        doesn't change during runtime."""
        cached = getattr(self, '_ffmpeg_cached', None)
        if cached is not None:
            return cached
        # Look relative to the app directory
        here = Path(__file__).resolve().parent.parent  # desktop-downloader/
        candidates = [
            here / "bin" / "ffmpeg",           # macOS binary
            here / "bin" / "ffmpeg.exe",        # Windows binary
            here / ".." / "ffmpeg",             # project root (macOS)
        ]
        result = "ffmpeg"  # fallback to PATH
        for c in candidates:
            if c.exists():
                result = str(c)
                break
        self._ffmpeg_cached = result
        return result

    def get_bilibili_credential_dict(self) -> dict:
        """Return Bilibili credential data for cookie manager."""
        return {
            "sessdata": self._data.get("bilibili_sessdata", ""),
            "bili_jct": self._data.get("bilibili_bili_jct", ""),
            "buvid3": self._data.get("bilibili_buvid3", ""),
        }

    def set_bilibili_credential(self, sessdata: str, bili_jct: str, buvid3: str):
        self._data["bilibili_sessdata"] = sessdata
        self._data["bilibili_bili_jct"] = bili_jct
        self._data["bilibili_buvid3"] = buvid3
        self.save()

    @property
    def clipboard_monitor_enabled(self) -> bool:
        return self._data.get("clipboard_monitor_enabled", False)

    @clipboard_monitor_enabled.setter
    def clipboard_monitor_enabled(self, value: bool):
        self._data["clipboard_monitor_enabled"] = value
        self.save()

    @property
    def notification_enabled(self) -> bool:
        return self._data.get("notification_enabled", True)

    @notification_enabled.setter
    def notification_enabled(self, value: bool):
        self._data["notification_enabled"] = value
        self.save()

    @property
    def notification_sound(self) -> bool:
        return self._data.get("notification_sound", True)

    @notification_sound.setter
    def notification_sound(self, value: bool):
        self._data["notification_sound"] = value
        self.save()

    @property
    def minimize_to_tray(self) -> bool:
        return self._data.get("minimize_to_tray", False)

    @minimize_to_tray.setter
    def minimize_to_tray(self, value: bool):
        self._data["minimize_to_tray"] = value
        self.save()

    @property
    def post_download_transcode(self) -> str:
        return self._data.get("post_download_transcode", "none")

    @post_download_transcode.setter
    def post_download_transcode(self, value: str):
        valid = ("none", "h264", "h265")
        if value not in valid:
            value = "none"
        self._data["post_download_transcode"] = value
        self.save()

    @property
    def schedule_enabled(self) -> bool:
        return self._data.get("schedule_enabled", False)

    @schedule_enabled.setter
    def schedule_enabled(self, value: bool):
        self._data["schedule_enabled"] = value
        self.save()

    @property
    def schedule_start(self) -> str:
        return self._data.get("schedule_start", "23:00")

    @schedule_start.setter
    def schedule_start(self, value: str):
        self._data["schedule_start"] = value
        self.save()

    @property
    def schedule_end(self) -> str:
        return self._data.get("schedule_end", "07:00")

    @schedule_end.setter
    def schedule_end(self, value: str):
        self._data["schedule_end"] = value
        self.save()

    @property
    def schedule_days(self) -> list[int]:
        return self._data.get("schedule_days", [0, 1, 2, 3, 4, 5, 6])

    @schedule_days.setter
    def schedule_days(self, value: list[int]):
        self._data["schedule_days"] = [d for d in value if 0 <= d <= 6]
        self.save()
