"""
WorkerMixin — shared worker lifecycle for QScrollArea pages.

Consolidates:
- Worker tracking list (prevents GC-dealloc-while-running crash)
- Periodic cleanup timer (collects finished workers)
- Signal disconnection helpers (safe for workers without all signal types)
- Zombie-worker list for safe cancellation
- Cover loader cancellation
- Page lifecycle hooks (on_page_left, is_busy, reset_to_idle)

Eliminates 4x identical copies of _track_worker, _collect_finished_workers,
_cancel_cover_loaders, and the cleanup-timer setup across HomePage, UpPage,
CollectionPage, SearchPage.
"""
import warnings

from PySide6.QtCore import QThread, QTimer


class WorkerMixin:
    """Mixin providing worker lifecycle management.

    Usage: ``class MyPage(QScrollArea, WorkerMixin):``
    Call ``WorkerMixin.__init_from__(self)`` inside the page's ``__init__``.

    Provides:
    - ``_workers``, ``_zombie_workers``, ``_cover_loaders`` lists
    - ``_cleanup_timer`` (fires every 15 s)
    - ``_track_worker()``
    - ``_collect_finished_workers()``
    - ``_disconnect_worker()``
    - ``_cancel_cover_loaders()``
    - ``_safe_reset()``
    - ``is_busy()``
    - ``on_page_left()``
    - ``reset_to_idle()``
    """

    _workers: list[QThread]
    _zombie_workers: list[QThread]
    _cover_loaders: list
    _cleanup_timer: QTimer

    @classmethod
    def __init_from__(cls, self_obj):
        """Call from the page's ``__init__`` (replaces cooperative MRO)."""
        self_obj._workers = []
        self_obj._zombie_workers = []
        self_obj._cover_loaders = []
        self_obj._cleanup_timer = QTimer(self_obj)
        self_obj._cleanup_timer.setInterval(15000)
        self_obj._cleanup_timer.timeout.connect(self_obj._collect_finished_workers)
        self_obj._cleanup_timer.start()
        return self_obj

    def _track_worker(self, worker: QThread) -> QThread:
        """Add worker to tracking list (prevents GC while thread runs)."""
        self._workers.append(worker)
        return worker

    def _collect_finished_workers(self):
        self._workers = [
            w for w in self._workers
            if hasattr(w, 'isRunning') and w.isRunning()
        ][-200:]
        self._zombie_workers = [
            w for w in self._zombie_workers
            if hasattr(w, 'isRunning') and w.isRunning()
        ][-200:]

    @staticmethod
    def _disconnect_worker(worker: QThread):
        """Safely disconnect all known signals on *worker*.

        Uses getattr to handle workers that don't define all signal types
        (e.g. CoverLoader has no 'error' signal).
        """
        for sig_name in ("loaded", "url_loaded", "finished", "error"):
            sig = getattr(worker, sig_name, None)
            if sig is not None:
                # CoverLoader QRunnable signals live on a proxy object,
                # not directly on the worker — disconnect via proxy instead.
                sigs_proxy = getattr(worker, "signals", None)
                if sigs_proxy is not None:
                    proxy_sig = getattr(sigs_proxy, sig_name, None)
                    if proxy_sig is not None:
                        try:
                            proxy_sig.disconnect()
                        except (TypeError, RuntimeError):
                            pass
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    try:
                        sig.disconnect()
                    except (TypeError, RuntimeError):
                        pass

    def _cancel_cover_loaders(self):
        """Cancel and disconnect all active CoverLoader (QRunnable) instances."""
        for loader in list(self._cover_loaders):
            loader.cancel()
            # QRunnable cannot own QObject signals — they live on the proxy.
            signals = getattr(loader, "signals", None)
            if signals is not None:
                for sig_name in ("url_loaded", "loaded"):
                    sig = getattr(signals, sig_name, None)
                    if sig is not None:
                        try:
                            sig.disconnect()
                        except (TypeError, RuntimeError):
                            pass
        self._cover_loaders.clear()

    def _safe_reset(self):
        """Cancel running workers and cover loaders. Never destroys a running QThread.

        Subclasses should override _on_safe_reset() to reset page-specific
        state (loading flags, progress timers, etc.) before calling this.
        """
        self._on_safe_reset()
        self._cancel_cover_loaders()
        for w in list(self._workers):
            if not hasattr(w, 'isRunning'):
                continue
            if w.isRunning():
                self._disconnect_worker(w)
                w.requestInterruption()
                if w.isRunning():
                    self._zombie_workers.append(w)
        self._workers = []
        self._zombie_workers = [
            w for w in self._zombie_workers
            if hasattr(w, 'isRunning') and w.isRunning()
        ]

    def _on_safe_reset(self):
        """Override in subclasses to reset page-specific state before worker cleanup."""
        pass

    def _is_running(self, obj) -> bool:
        """Check if an object is still running (QThread or QRunnable)."""
        if hasattr(obj, "isRunning"):
            return obj.isRunning()
        return not getattr(obj, "_cancelled", True)

    def is_busy(self) -> bool:
        """Return True if any workers or cover loaders are still running."""
        return any(self._is_running(w) for w in self._workers) or \
               any(self._is_running(l) for l in self._cover_loaders)

    def on_page_left(self):
        """Called when user navigates away from this page.

        Cancels in-flight workers and cover loaders to free resources.
        Results remain visible for when the user returns.
        Override in subclasses for custom behavior (e.g. skip cleanup
        during batch mode).
        """
        self._safe_reset()

    def reset_to_idle(self):
        """Reset page to idle state after an error.

        Ensures UI elements (buttons, loading spinners) are restored to
        a usable state. Override in subclasses to reset page-specific UI.
        """
        self._safe_reset()
