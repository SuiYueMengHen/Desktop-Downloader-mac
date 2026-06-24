"""Download manager: Bilibili DASH+ffmpeg direct download via QThread workers."""
import logging
import os
import time
import threading
import shutil
import subprocess as sp
from collections import deque
from functools import partial
from pathlib import Path
from typing import Optional, Callable
from datetime import datetime, time as dtime

import httpx
from PySide6.QtCore import QThread, Signal, QObject, QTimer

logger = logging.getLogger(__name__)

from app.config import Config
from app.history_manager import HistoryManager
from app.platforms.base import DownloadTask
from app.utils.helpers import sanitize_filename

# Module-level httpx client shared across all download workers.
# Prevents TCP connection setup per worker and allows connection reuse.
_DL_HTTP = httpx.Client(
    timeout=httpx.Timeout(600.0, connect=15.0),
    follow_redirects=True,
    limits=httpx.Limits(max_keepalive_connections=4, max_connections=8),
)


class DownloadSignals(QObject):
    progress = Signal(object)
    completed = Signal(object)
    error = Signal(object)


class DownloadProgress:
    def __init__(self, task_id: str, filename: str, total_size: int = 0):
        self.task_id = task_id
        self.filename = filename
        self.total_size = total_size
        self.downloaded = 0
        self.speed = 0.0
        self.status = "pending"
        self.error_msg = ""
        self._lock = threading.Lock()
        self._start_time = 0.0
        self._output_file = ""   # full path to output file, set on completion

    @property
    def progress_pct(self) -> float:
        if self.total_size <= 0: return 0.0
        return min(100.0, (self.downloaded / self.total_size) * 100.0)


# ── Bilibili Direct Worker (httpx streams + ffmpeg merge) ──

class BilibiliDirectWorker(QThread):
    _ps = Signal(object)  # progress
    _fs = Signal(object)  # finished
    _es = Signal(object)  # error

    def __init__(self, tid: str, v_url: str, a_url: str, out: str, ff: str,
                 referer: str = "", speed_limit_ref: Optional[list] = None,
                 audio_only: bool = False, transcode_ref: Optional[list] = None):
        super().__init__()
        self.tid = tid
        self.v_url = v_url
        self.a_url = a_url
        self.out = out
        self.ff = ff
        self.referer = referer
        self._cancel = False
        self.audio_only = audio_only
        # Shared mutable reference: update DownloadManager.speed_limit to take effect live
        self._speed_ref = speed_limit_ref or [0]
        # Shared mutable reference: read by worker at transcode time (live-updatable)
        self._transcode_ref = transcode_ref or [""]
        self.progress = DownloadProgress(tid, os.path.basename(out))
        self.signals = DownloadSignals()
        self._ps.connect(self.signals.progress)
        self._fs.connect(self.signals.completed)
        self._es.connect(self.signals.error)

    def cancel(self):
        self._cancel = True

    def run(self):
        self.progress.status = "downloading"
        self.progress._start_time = time.time()
        tmp = None
        try:
            tmp = Path(self.out).parent / f".tmp_{self.tid}"; tmp.mkdir(parents=True, exist_ok=True)
            vt = tmp / "v.mp4"; at = tmp / "a.mp4"

            # Bilibili CDN requires Referer and User-Agent headers
            headers = {
                "Referer": self.referer or "https://www.bilibili.com",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            }

            # Progress signal throttle state
            _last_emit = time.time()
            _emit_interval = 0.25  # max 4 updates/sec per download

            def _emit_progress(d: int, total: int):
                nonlocal _last_emit
                now = time.time()
                self.progress.total_size = total
                self.progress.downloaded = d
                self.progress.speed = d / max(0.1, now - self.progress._start_time)
                if now - _last_emit >= _emit_interval:
                    _last_emit = now
                    self._ps.emit(self.progress)

            def dl(url: str, path: Path) -> bool:
                max_rate = self._speed_ref[0] * 1024  # KB/s → bytes/s, live-updatable
                with _DL_HTTP.stream("GET", url, headers=headers) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("content-length", 0)) or 0
                    with open(path, "wb") as f:
                        d = 0
                        # Token bucket rate limiter
                        bucket = max_rate
                        last_refill = time.time()
                        for chunk in r.iter_bytes(65536):
                            if self._cancel:
                                return False
                            if not chunk:
                                continue
                            if max_rate > 0:
                                now = time.time()
                                elapsed = now - last_refill
                                bucket += elapsed * max_rate
                                if bucket > max_rate:
                                    bucket = max_rate
                                last_refill = now
                                if bucket < len(chunk):
                                    deficit = len(chunk) - bucket
                                    time.sleep(deficit / max_rate)
                                    now = time.time()
                                    elapsed = now - last_refill
                                    bucket += elapsed * max_rate
                                    if bucket > max_rate:
                                        bucket = max_rate
                                    last_refill = now
                                bucket -= len(chunk)
                            f.write(chunk)
                            d += len(chunk)
                            if total:
                                _emit_progress(d, total)
                return path.exists() and path.stat().st_size > 0

            # ── Audio-only path ──
            if self.audio_only:
                if not self.a_url:
                    raise Exception("音频提取模式：无法获取音频流地址")
                if not dl(self.a_url, at):
                    raise Exception("音频流下载失败")
                if self._cancel:
                    return
                self.progress.speed = 0
                self._ps.emit(self.progress)
                final = Path(str(self.out).replace("%(ext)s", "mp3"))
                # Convert downloaded audio to MP3 via ffmpeg
                cmd = [
                    self.ff, "-y", "-i", str(at),
                    "-c:a", "libmp3lame", "-q:a", "2",
                    str(final),
                ]
                p = sp.run(cmd, capture_output=True, text=True)
                if p.returncode != 0:
                    raise Exception(f"FFmpeg音频转换失败: {p.stderr[:200]}")
                if tmp and tmp.exists():
                    shutil.rmtree(tmp, ignore_errors=True)
                if final.exists() and final.stat().st_size > 0:
                    self.progress.total_size = final.stat().st_size
                    self.progress.downloaded = self.progress.total_size
                    self.progress.status = "completed"
                    self.progress.speed = 0
                    self.progress._output_file = str(final)
                    self._fs.emit(self.progress)
                    return
                raise Exception("MP3输出文件为空")
            # ── Normal video path ──
            final = Path(self.out.replace("%(ext)s", "mp4"))
            if not dl(self.v_url, vt): raise Exception("视频流下载失败")
            if self.a_url and not dl(self.a_url, at): raise Exception("音频流下载失败")
            if self._cancel: return

            self.progress.speed = 0; self._ps.emit(self.progress)
            # Merge - try fast copy first, fall back to re-encode
            cmd = [self.ff, "-y", "-i", str(vt)]
            has_audio = at.exists() and at.stat().st_size > 0
            if has_audio:
                cmd += ["-i", str(at), "-c:v", "copy", "-c:a", "copy"]
            else:
                cmd += ["-c", "copy"]
            cmd.append(str(final))
            p = sp.run(cmd, capture_output=True, text=True)
            if p.returncode != 0:
                cmd2 = [self.ff, "-y", "-i", str(vt)]
                if has_audio:
                    cmd2 += ["-i", str(at)]
                cmd2 += ["-c:v", "libx264", "-c:a", "aac", "-crf", "23", str(final)]
                p2 = sp.run(cmd2, capture_output=True, text=True)
                if p2.returncode != 0:
                    raise Exception(f"FFmpeg合并失败: {p2.stderr[:200]}")
            if tmp and tmp.exists(): shutil.rmtree(tmp, ignore_errors=True)

            # ── Post-download transcode ──
            if final.exists() and final.stat().st_size > 0:
                tc = self._transcode_ref[0] if self._transcode_ref else ""
                if tc == "h264":
                    tmp_out = final.with_suffix(".tmp.mp4")
                    cmd_tc = [
                        self.ff, "-y", "-i", str(final),
                        "-c:v", "libx264", "-c:a", "aac",
                        "-crf", "23", "-preset", "fast",
                        str(tmp_out),
                    ]
                    p_tc = sp.run(cmd_tc, capture_output=True, text=True)
                    if p_tc.returncode == 0 and tmp_out.exists():
                        shutil.move(str(tmp_out), str(final))
                elif tc == "h265":
                    tmp_out = final.with_suffix(".tmp.mp4")
                    cmd_tc = [
                        self.ff, "-y", "-i", str(final),
                        "-c:v", "libx265", "-c:a", "aac",
                        "-crf", "28", "-preset", "fast",
                        str(tmp_out),
                    ]
                    p_tc = sp.run(cmd_tc, capture_output=True, text=True)
                    if p_tc.returncode == 0 and tmp_out.exists():
                        shutil.move(str(tmp_out), str(final))

            if final.exists() and final.stat().st_size > 0:
                self.progress.total_size = final.stat().st_size
                self.progress.downloaded = self.progress.total_size
                self.progress.status = "completed"; self.progress.speed = 0
                self.progress._output_file = str(final)
                self._fs.emit(self.progress)
            else:
                raise Exception("输出文件为空")
        except Exception as e:
            # Clean up temp files on error
            if tmp and tmp.exists(): shutil.rmtree(tmp, ignore_errors=True)
            self.progress.status = "error"; self.progress.error_msg = str(e)
            self._es.emit(self.progress)


# ── Manager ──

class DownloadManager(QObject):
    task_added = Signal(str, str, str)  # tid, filename, platform

    def __init__(self, mc: int = 3):
        super().__init__()
        self.config = Config()
        self.max_concurrent = mc
        self._queue: deque = deque()
        self._workers: dict = {}
        self._completed = []
        self._pcb = []
        self._ccb = []
        self._ecb = []
        self._history_manager = HistoryManager()

        # Shared speed limit reference — updated by setter, read by running workers
        self._speed_limit_ref = [self.config.download_speed_limit]
        # Shared transcode mode reference — read at post-merge time
        self._transcode_ref = [self.config.post_download_transcode]

        # Schedule check timer (every 60 seconds)
        self._schedule_timer = QTimer(self)
        self._schedule_timer.setInterval(60000)
        self._schedule_timer.timeout.connect(self._check_schedule)
        if self.config.schedule_enabled:
            self._schedule_timer.start()

    @property
    def speed_limit(self) -> int:
        return self._speed_limit_ref[0]

    @speed_limit.setter
    def speed_limit(self, value: int):
        self._speed_limit_ref[0] = max(0, value)

    @property
    def transcode_mode(self) -> str:
        return self._transcode_ref[0] or "none"

    @transcode_mode.setter
    def transcode_mode(self, value: str):
        self._transcode_ref[0] = value

    # ── Download schedule ──

    def on_schedule_changed(self):
        """Called when schedule settings change — restart timer."""
        # Invalidate schedule cache when settings change
        if hasattr(self, '_schedule_cache'):
            self._schedule_cache.clear()
        if self.config.schedule_enabled:
            if not self._schedule_timer.isActive():
                self._schedule_timer.start()
            self._check_schedule()
        else:
            self._schedule_timer.stop()
            self._schedule()

    def _check_schedule(self):
        """Periodic check: if we just entered the schedule window, start queued tasks."""
        if not self.config.schedule_enabled:
            return
        if self._is_in_schedule_window():
            self._schedule()

    def _is_in_schedule_window(self) -> bool:
        """Check if current time falls within the configured download schedule."""
        if not self.config.schedule_enabled:
            return True
        now = datetime.now()
        # Check day of week
        weekday = now.weekday()  # Monday=0
        if weekday not in self.config.schedule_days:
            return False
        # Check time (cached parsing)
        now_time = now.time()
        cache_key = f"{self.config.schedule_start}-{self.config.schedule_end}"
        if not hasattr(self, '_schedule_cache'):
            self._schedule_cache = {}
        if cache_key not in self._schedule_cache:
            start_str = self.config.schedule_start
            end_str = self.config.schedule_end
            try:
                start_h, start_m = map(int, start_str.split(":"))
                end_h, end_m = map(int, end_str.split(":"))
                self._schedule_cache[cache_key] = (dtime(start_h, start_m), dtime(end_h, end_m))
            except (ValueError, AttributeError):
                return True
        start, end = self._schedule_cache[cache_key]
        if start <= end:
            # Normal range: e.g. 08:00 ~ 22:00
            return start <= now_time <= end
        else:
            # Overnight range: e.g. 23:00 ~ 07:00
            return now_time >= start or now_time <= end

    def on_progress(self, cb):
        self._pcb.append(cb)

    def on_completed(self, cb):
        self._ccb.append(cb)

    def on_error(self, cb):
        self._ecb.append(cb)

    def add_task(self, task: DownloadTask) -> str:
        page_suffix = f"_{task.page_label}" if task.page_label else ""
        tid = f"{task.platform}_{task.video_info.video_id}{page_suffix}_{int(time.time() * 1000)}"
        safe = sanitize_filename(task.video_info.title)
        if task.page_label:
            safe = f"{safe}_{task.page_label}"
        suffix = "mp3" if task.audio_only else "%(ext)s"
        qs = task.video_stream.quality.value if task.video_stream else "auto"
        if task.audio_only:
            qs = "mp3"
        out = str(Path(self.config.download_path) / f"{safe}_{qs}.{suffix}")
        self._queue.append((tid, task, out))
        self.task_added.emit(tid, safe, task.platform)
        self._schedule()
        return tid

    def _schedule(self):
        act = len(self._workers)
        in_window = self._is_in_schedule_window()
        while act < self.max_concurrent and self._queue:
            if not in_window:
                break  # Outside schedule window — don't start new downloads
            tid, task, out = self._queue.popleft()
            act += 1
            # Ensure output directory exists
            out_dir = Path(out).parent
            out_dir.mkdir(parents=True, exist_ok=True)
            if task.platform == "bilibili":
                vs = task.video_stream
                au = task.audio_stream
                vu = vs.url if vs else ""
                au_url = au.url if au else ""
                if not task.audio_only and not vu:
                    self._on_err(tid, DownloadProgress(tid, ""))
                    continue
                referer = task.video_info.raw_data.get("webpage_url", "") or \
                          f"https://www.bilibili.com/video/{task.video_info.video_id}"
                w = BilibiliDirectWorker(tid, vu, au_url, out, self.config.ffmpeg_location,
                                          referer, self._speed_limit_ref,
                                          audio_only=task.audio_only,
                                          transcode_ref=self._transcode_ref)
            else:
                self._on_err(tid, DownloadProgress(tid, task.video_info.title))
                continue
            # Attach task and platform info to progress for UI and history
            w.progress._platform = task.platform
            w.progress._task = task
            w.signals.progress.connect(partial(self._on_prog, tid))
            w.signals.completed.connect(partial(self._on_done, tid))
            w.signals.error.connect(partial(self._on_err, tid))
            self._workers[tid] = w
            w.start()

    def _on_prog(self, tid, p):
        for cb in self._pcb:
            try:
                cb(p)
            except Exception as exc:
                logger.warning("Progress callback failed: %s", exc)

    def _on_done(self, tid, p):
        self._workers.pop(tid, None)
        # Limit completed list to prevent memory growth
        self._completed.append(p)
        if len(self._completed) > 1000:
            self._completed = self._completed[-1000:]
        # Record download history
        task: Optional[DownloadTask] = getattr(p, '_task', None)
        if task and p._output_file:
            try:
                file_size = 0
                if os.path.exists(p._output_file):
                    file_size = os.path.getsize(p._output_file)
                pages = task.video_info.raw_data.get("pages", [])
                page_count = task.video_info.raw_data.get("total_pages", 0) or len(pages)
                self._history_manager.add_entry(
                    platform=task.platform,
                    video_id=task.video_info.video_id,
                    title=task.video_info.title,
                    quality=task.video_stream.quality.value if task.video_stream else "",
                    file_path=p._output_file,
                    file_size=file_size,
                    duration=task.video_info.duration,
                    page_label=task.page_label,
                    page_count=page_count,
                )
            except Exception as exc:
                logger.warning("Failed to record download history: %s", exc)
        for cb in self._ccb:
            try:
                cb(p)
            except Exception as exc:
                logger.warning("Completion callback failed: %s", exc)
        self._schedule()

    def _on_err(self, tid, p):
        self._workers.pop(tid, None)
        for cb in self._ecb:
            try:
                cb(p)
            except Exception as exc:
                logger.warning("Error callback failed: %s", exc)
        self._schedule()

    def pause_task(self, tid):
        if tid in self._workers:
            self._workers[tid].cancel()
            self._workers[tid].wait(3000)
            self._workers.pop(tid, None)

    def remove_task(self, tid):
        """Remove a single task: cancel if running, or dequeue if queued."""
        if tid in self._workers:
            self._workers[tid].cancel()
            self._workers[tid].wait(1000)
            self._workers.pop(tid, None)
        else:
            self._queue = deque(e for e in self._queue if e[0] != tid)
        self._completed[:] = [p for p in self._completed if p.task_id != tid]

    def stop_all(self):
        """Cancel all running workers and requeue their tasks for later resume."""
        for tid, w in list(self._workers.items()):
            w.cancel()
            w.wait(2000)
            task = getattr(w.progress, '_task', None)
            if task:
                self._queue.appendleft((tid, task, w.out))
            self._workers.pop(tid, None)

    def cancel_all(self):
        """Cancel all downloads and clear everything."""
        for w in self._workers.values():
            w.cancel()
            w.wait(500)
        self._workers.clear()
        self._queue.clear()
        self._completed.clear()

    def resume_all(self):
        """Start/resume all queued downloads."""
        self._schedule()

    def stop(self):
        for w in self._workers.values():
            w.cancel()
            w.wait(2000)
        self._workers.clear()
        self._queue.clear()

    def get_progress(self, tid):
        w = self._workers.get(tid)
        return w.progress if w else None

    def get_all_progress(self):
        return [w.progress for w in self._workers.values()]

    def get_completed(self):
        return self._completed
