"""
Helper utilities.
"""
import os
import re
import platform
from pathlib import Path
from typing import Optional


def sanitize_filename(name: str) -> str:
    """Remove characters that are invalid in filenames."""
    # Windows: \ / : * ? " < > |
    # macOS/Linux: /
    invalid_chars = r'[\\/:*?"<>|]'
    name = re.sub(invalid_chars, "", name)
    name = name.strip()
    if not name:
        name = "untitled"
    # Limit length (Windows MAX_PATH is 255 per component)
    max_len = 200
    if len(name) > max_len:
        name = name[:max_len]
    return name


def detect_platform(url: str) -> Optional[str]:
    """Detect the platform from a URL."""
    url_lower = url.strip().lower()

    if any(d in url_lower for d in ["bilibili.com", "b23.tv"]):
        return "bilibili"
    return None


def detect_url_type(url: str) -> Optional[str]:
    """Detect whether a URL is a video URL, UP主 space, or collection URL.

    Returns:
        "space" for UP主 space URLs (space.bilibili.com/UID)
        "collection" for UP主 collection/series URLs (space.bilibili.com/UID/lists/XXXX)
        "video" for video URLs (bilibili.com/video/BVxxx, b23.tv)
        None if not a recognized bilibili URL
    """
    url_lower = url.strip().lower()
    if "bilibili.com" not in url_lower and "b23.tv" not in url_lower:
        return None

    # Collection / series URL pattern: space.bilibili.com/UID/lists/SERIES_ID
    if "space.bilibili.com" in url_lower and "/lists/" in url_lower:
        return "collection"

    # UP主 space URL pattern
    if "space.bilibili.com" in url_lower:
        return "space"

    # Video URL patterns
    if "/video/" in url_lower or "b23.tv" in url_lower:
        return "video"

    # Default to video for other bilibili URLs
    return "video"


def extract_series_id(url: str) -> Optional[int]:
    """Extract collection/series ID from a Bilibili collection URL.

    URL format: https://space.bilibili.com/{uid}/lists/{series_id}
    """
    m = re.search(r'/lists/(\d+)', url)
    if m:
        return int(m.group(1))
    return None


def ensure_dir(path: str) -> Path:
    """Ensure a directory exists and return Path object."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes < 0:
        return "未知"
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"


def format_speed(bytes_per_sec: float) -> str:
    """Format download speed."""
    if bytes_per_sec < 0:
        return "---"
    return format_size(bytes_per_sec) + "/s"


def format_duration(seconds: int) -> str:
    """Format duration in seconds to HH:MM:SS or MM:SS."""
    if seconds <= 0:
        return "00:00"
    h, remainder = divmod(int(seconds), 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def theme_color(light: str, dark: str) -> str:
    """Return the appropriate color based on current theme."""
    from qfluentwidgets import isDarkTheme
    return dark if isDarkTheme() else light


def muted_text_color() -> str:
    """Theme-aware muted text color for secondary labels."""
    return theme_color("#888", "#999")


def secondary_text_color() -> str:
    """Theme-aware secondary text color (slightly lighter than muted)."""
    return theme_color("#999", "#aaa")


def normal_text_color() -> str:
    """Theme-aware normal text color for status labels."""
    return theme_color("#555", "#ccc")


def configure_smooth_scroll(scroll_area) -> None:
    """Configure a SmoothScrollArea for optimal scrolling on the current platform.

    On macOS, trackpad events have non-120 delta values, which qfluentwidgets'
    SmoothScrollArea bypasses (falling back to Qt native). This helper:
    - Reduces animation duration for snappier mouse-wheel scrolling
    - Sets finer scroll steps for better trackpad precision
    - Enables pixel-level scrolling on macOS
    """
    from PySide6.QtCore import Qt, QEasingCurve
    from PySide6.QtWidgets import QAbstractScrollArea

    # Shorter animation for snappier feel (default is 500ms which feels sluggish)
    if hasattr(scroll_area, 'setScrollAnimation'):
        scroll_area.setScrollAnimation(
            Qt.Vertical, 250, QEasingCurve.OutCubic
        )
        scroll_area.setScrollAnimation(
            Qt.Horizontal, 250, QEasingCurve.OutCubic
        )

    # Finer scroll steps for trackpad precision
    vbar = scroll_area.verticalScrollBar()
    if vbar:
        vbar.setSingleStep(16)
        # On macOS, enable pixel-level scrolling for smooth trackpad experience
        if platform.system() == "Darwin":
            scroll_area.setHorizontalScrollBarPolicy(
                Qt.ScrollBarAsNeeded
            )

    hbar = scroll_area.horizontalScrollBar()
    if hbar:
        hbar.setSingleStep(16)

    # Ensure the scroll area doesn't eat trackpad events
    scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
