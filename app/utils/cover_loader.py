"""Shared CoverLoader for loading cover images in background threads.

Uses a module-level httpx.Client with connection pooling to reuse TCP
connections across repeated cover loads. An in-memory LRU cache avoids
redundant network requests for the same URL. A batch-aware delay mechanism
prevents thread-storm when many cards are created at once.
"""
import threading
from functools import lru_cache

import httpx
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

# Shared connection pool: up to 10 keep-alive connections, 30s timeout.
_HTTP = httpx.Client(
    timeout=httpx.Timeout(10.0, connect=5.0),
    follow_redirects=True,
    limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
)

# Limit concurrent cover-load threads to avoid thread explosion in batch mode
_COVER_SEM = threading.BoundedSemaphore(6)

# In-memory LRU cache for cover image bytes (up to 200 entries ≈ ~50 MB).
@lru_cache(maxsize=200)
def _fetch_cover(url: str) -> bytes:
    resp = _HTTP.get(url)
    resp.raise_for_status()
    return resp.content


class CoverSignals(QObject):
    loaded = Signal(bytes)
    url_loaded = Signal(str, bytes)


class CoverLoader(QRunnable):
    """Non-blocking cover image loader (runs via QThreadPool)."""

    def __init__(self, url: str, key: str = "", signals: CoverSignals | None = None):
        super().__init__()
        self.url = url
        self.key = key
        self.signals = signals or CoverSignals()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self):
        if not _COVER_SEM.acquire(timeout=30):
            return
        try:
            data = _fetch_cover(self.url)
            if data and not self._cancelled:
                if self.key:
                    self.signals.url_loaded.emit(self.key, data)
                else:
                    self.signals.loaded.emit(data)
        except httpx.HTTPError:
            pass
        finally:
            _COVER_SEM.release()


def start_cover_loader(url: str, signals: CoverSignals, key: str = "",
                       delay_ms: int = 0) -> CoverLoader:
    """Create and start a CoverLoader, optionally with a delay.

    When *delay_ms* > 0, the loader is queued via QTimer so the UI has
    time to settle before the network request begins.  Returns the
    CoverLoader (caller can cancel() it if needed).
    """
    loader = CoverLoader(url, key, signals)
    if delay_ms > 0:
        QTimer.singleShot(delay_ms, lambda: QThreadPool.globalInstance().start(loader))
    else:
        QThreadPool.globalInstance().start(loader)
    return loader
