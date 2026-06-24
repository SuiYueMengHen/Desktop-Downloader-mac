"""
Download history manager - JSON-based history persistence.

Batch saves are coalesced via a simple time-based debounce:
repeated calls within 500ms produce only one disk write.
"""
import json
import time
import uuid
from pathlib import Path

from app.config import Config

_DEBOUNCE_S = 0.5  # minimum interval between disk writes


class HistoryManager:
    """Manages download history as JSON file in config directory."""

    def __init__(self):
        self.config = Config()
        self._history_file = self.config.config_dir / "history.json"
        self._entries: list[dict] = []
        self._last_save_time: float = 0.0
        self.load()

    @property
    def history_file(self) -> Path:
        return self._history_file

    def load(self):
        if self._history_file.exists():
            try:
                with open(self._history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._entries = data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError):
                self._entries = []
        else:
            self._entries = []

    def save(self):
        """Debounced write — coalesces burst calls into a single disk write."""
        now = time.monotonic()
        if now - self._last_save_time < _DEBOUNCE_S:
            return  # skip — last write was recent
        self._last_save_time = now
        try:
            self._history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._history_file, "w", encoding="utf-8") as f:
                json.dump(self._entries, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

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

    def clear_all(self):
        self._entries = []
        self.save()
