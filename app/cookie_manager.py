"""
Cookie/Session management for platform authentication.
Supports storing credentials and providing them to platform adapters.
"""
import json
from typing import Optional

from app.config import Config


class CookieManager:
    """Manages authentication cookies for all platforms."""

    def __init__(self):
        self.config = Config()
        self._bilibili_cred = None

    # ── Bilibili ──────────────────────────────────────────

    @property
    def bilibili_sessdata(self) -> str:
        return self.config.get("bilibili_sessdata", "")

    @bilibili_sessdata.setter
    def bilibili_sessdata(self, value: str):
        self.config.set("bilibili_sessdata", value)

    @property
    def bilibili_bili_jct(self) -> str:
        return self.config.get("bilibili_bili_jct", "")

    @bilibili_bili_jct.setter
    def bilibili_bili_jct(self, value: str):
        self.config.set("bilibili_bili_jct", value)

    @property
    def bilibili_buvid3(self) -> str:
        return self.config.get("bilibili_buvid3", "")

    @bilibili_buvid3.setter
    def bilibili_buvid3(self, value: str):
        self.config.set("bilibili_buvid3", value)

    def is_bilibili_logged_in(self) -> bool:
        """Check if Bilibili credentials are available."""
        return bool(self.bilibili_sessdata and self.bilibili_bili_jct)

    def clear_bilibili(self):
        """Clear Bilibili credentials."""
        self.config.set("bilibili_sessdata", "")
        self.config.set("bilibili_bili_jct", "")
        self.config.set("bilibili_buvid3", "")

    # ── Cookie file I/O ──────────────────────────────────

    def save_cookies_to_file(self, platform: str, cookies: dict):
        """Save cookies for a platform to a JSON file."""
        path = self.config.cookie_dir / f"{platform}_cookies.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2, ensure_ascii=False)

    def load_cookies_from_file(self, platform: str) -> Optional[dict]:
        """Load cookies for a platform from JSON file."""
        path = self.config.cookie_dir / f"{platform}_cookies.json"
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return None
        return None
