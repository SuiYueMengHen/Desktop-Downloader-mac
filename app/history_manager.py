"""
Download history manager - JSON-based history persistence.

Saves are debounced via threading.Timer — repeated calls within 500ms
produce only one disk write, and the last write is never dropped.
"""
import json
import logging
import threading
import time
import uuid
from pathlib import Path

from app.config import Config

logger = logging.getLogger(__name__)


class HistoryManager:
    """Manages download history as JSON file in config directory."""

    def __init__(self):
        self.config = Config()
        self._history_file = self.config.config_dir / "history.json"
        self._entries: list[dict] = []
        self._dirty = False
        self._save_timer: threading.Timer | None = None
        self._save_lock = threading.Lock()
        self._debounce_s = 0.5
        self.load()

    @property
    def history_file(self) -> Path:
        return self._history_file

    def load(self) -> None:
        if self._history_file.exists():
            try:
                with open(self._history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    with self._save_lock:
                        self._entries = data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("History file corrupt, resetting: %s", e)
                with self._save_lock:
                    self._entries = []
        else:
            with self._save_lock:
                self._entries = []

    def _do_save(self) -> None:
        """Actual disk write — called by debounce timer."""
        try:
            self._history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._history_file, "w", encoding="utf-8") as f:
                json.dump(self._entries, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.warning("Failed to save history: %s", e)
        with self._save_lock:
            self._dirty = False

    def _schedule_save(self) -> None:
        """Debounced save — coalesces burst calls into a single disk write."""
        if self._save_timer is not None and self._save_timer.is_alive():
            return
        self._save_timer = threading.Timer(self._debounce_s, self._do_save)
        self._save_timer.daemon = True
        self._save_timer.start()

    def save(self) -> None:
        """Mark dirty and schedule a debounced write. Never drops data."""
        with self._save_lock:
            was_clean = not self._dirty
            self._dirty = True
        if was_clean:
            self._schedule_save()

    def add_entry(self, platform: str, video_id: str, title: str,
                  quality: str, file_path: str, file_size: int,
                  duration: int, page_label: str = "",
                  page_count: int = 0) -> str:
        """Add a history entry and return its task_id."""
        task_id = str(uuid.uuid4())[:12]
        entry = {
            "task_id": task_id,
            "platform": platform,
            "video_id": video_id,
            "title": title,
            "quality": quality,
            "file_path": file_path,
            "file_size": file_size,
            "duration": duration,
            "page_label": page_label,
            "page_count": page_count,
            "timestamp": time.time(),
        }
        with self._save_lock:
            self._entries.insert(0, entry)  # newest first
        self.save()
        return task_id

    def get_all(self) -> list[dict]:
        return list(self._entries)

    def search(self, query: str) -> list[dict]:
        """Search history by title or video_id."""
        if not query:
            return self.get_all()
        q = query.lower().strip()
        return [
            e for e in self._entries
            if q in e.get("title", "").lower()
            or q in e.get("video_id", "").lower()
        ]

    def delete(self, task_id: str) -> bool:
        count = len(self._entries)
        self._entries = [e for e in self._entries if e.get("task_id") != task_id]
        if len(self._entries) < count:
            self.save()
            return True
        return False

    def delete_many(self, task_ids: list[str]) -> int:
        """Delete all entries matching the given task IDs. Returns count deleted."""
        original_count = len(self._entries)
        id_set = set(task_ids)
        self._entries = [e for e in self._entries if e.get("task_id") not in id_set]
        deleted = original_count - len(self._entries)
        if deleted > 0:
            self.save()
        return deleted

    def clear_all(self) -> None:
        with self._save_lock:
            self._entries = []
        self.save()
