"""Shared CoverLoader for loading cover images in background threads.

Uses a module-level httpx.Client with connection pooling to reuse TCP
connections across repeated cover loads, reducing latency and system resource
usage.  An in-memory LRU cache avoids redundant network requests for the same
URL (e.g. when re-entering a page that shows the same covers).
"""
from functools import lru_cache

import httpx
from PySide6.QtCore import QThread, Signal

# Shared connection pool: up to 10 keep-alive connections, 30s timeout.
_HTTP = httpx.Client(
    timeout=httpx.Timeout(10.0, connect=5.0),
    follow_redirects=True,
    limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
)

# In-memory LRU cache for cover image bytes (up to 200 entries ≈ ~50 MB).
@lru_cache(maxsize=200)
def _fetch_cover(url: str) -> bytes:
    """Download cover bytes; cached across calls for the same URL."""
    resp = _HTTP.get(url)
    resp.raise_for_status()
    return resp.content


class CoverLoader(QThread):
    """Non-blocking cover image loader.
    Emits raw image bytes from background thread.
    QPixmap must only be created on the GUI thread (Qt thread-safety rule).
    """
    loaded = Signal(bytes)  # raw image bytes, NOT QPixmap
    url_loaded = Signal(str, bytes)  # key, data

    def __init__(self, url: str, key: str = ""):
        super().__init__()
        self.url = url
        self.key = key

    def run(self):
        try:
            data = _fetch_cover(self.url)
            if data and not self.isInterruptionRequested():
                if self.key:
                    self.url_loaded.emit(self.key, data)
                else:
                    self.loaded.emit(data)
        except httpx.HTTPError:
            pass  # cover loading is best-effort; failure is non-critical
