"""
Update checker — checks GitHub Releases for a newer version.

On startup, runs a background thread to fetch the latest release tag
from the GitHub API. If a newer version is found, emits a signal
so the UI can show an update-available banner.
"""
import logging
import re
import threading
import urllib.request
import urllib.error
import json
from typing import Optional

from PySide6.QtCore import QObject, Signal

from app import __version__

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
_OWNER = "user"
_REPO = "desktop-downloader"


def _parse_version(tag: str) -> tuple[int, ...]:
    """Parse 'v1.2.3' or '1.2.3' into (1, 2, 3). Returns empty tuple on failure."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", tag)
    if m:
        return tuple(int(g) for g in m.groups())
    return ()


class UpdateChecker(QObject):
    """Checks for app updates in a background thread."""

    update_available = Signal(str, str)  # latest_version, download_url

    def __init__(self, owner: str = _OWNER, repo: str = _REPO, parent=None):
        super().__init__(parent)
        self._owner = owner
        self._repo = repo
        self._current = _parse_version(__version__)

    def check(self) -> None:
        """Run the check in a background thread (non-blocking)."""
        t = threading.Thread(target=self._do_check, daemon=True)
        t.start()

    def _do_check(self) -> None:
        """Fetch latest release info from GitHub API."""
        url = _GITHUB_API.format(owner=self._owner, repo=self._repo)
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "DesktopDownloader"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
            logger.debug("Update check failed: %s", e)
            return

        tag = data.get("tag_name", "")
        latest = _parse_version(tag)
        if not latest or latest <= self._current:
            return

        # Find a download URL for the .dmg asset
        download_url = ""
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if name.endswith(".dmg"):
                download_url = asset.get("browser_download_url", "")
                break

        logger.info("Update available: %s (current: %s)", tag, __version__)
        self.update_available.emit(tag.lstrip("v"), download_url)
