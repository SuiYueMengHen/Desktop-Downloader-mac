"""
AsyncWorker base class — eliminates redundant asyncio.new_event_loop()
boilerplate across 7 QThread subclasses.
"""
import sys
import asyncio
import traceback

from PySide6.QtCore import QThread, Signal


class AsyncWorker(QThread):
    """Worker that runs a single async function in a dedicated event loop.

    Subclasses implement ``async def work(self) -> object``.
    Emits ``finished(result)`` on success, ``error(msg)`` on failure.
    Respects ``isInterruptionRequested()`` to avoid emitting after cancel.
    """

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    async def work(self):
        raise NotImplementedError

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.work())
            loop.close()
            if not self.isInterruptionRequested():
                self.finished.emit(result)
        except Exception as e:
            # Print full traceback to terminal for debugging
            print(f"[AsyncWorker ERROR] {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            if not self.isInterruptionRequested():
                self.error.emit(str(e))
