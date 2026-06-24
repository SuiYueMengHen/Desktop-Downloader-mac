"""
Abstract base class for all platform adapters.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class VideoQuality(Enum):
    """Standardized video quality levels."""
    UNKNOWN = "unknown"
    Q_144P = "144p"
    Q_240P = "240p"
    Q_360P = "360p"
    Q_480P = "480p"
    Q_540P = "540p"
    Q_720P = "720p"
    Q_1080P = "1080p"
    Q_1080P_HIGH_BITRATE = "1080p_high_bitrate"  # 1080P 高码率
    Q_1440P = "1440p"  # 2K
    Q_2160P = "2160p"  # 4K
    Q_4320P = "4320p"  # 8K


@dataclass
class VideoInfo:
    """Unified video information from any platform."""
    platform: str
    video_id: str
    title: str
    description: str = ""
    duration: int = 0           # seconds
    cover_url: str = ""
    author_name: str = ""
    author_uid: str = ""
    available_qualities: list[VideoQuality] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)


@dataclass
class MediaStream:
    """A downloadable media stream (video or audio)."""
    url: str
    quality: VideoQuality = VideoQuality.UNKNOWN
    mime_type: str = ""
    codecs: str = ""
    width: int = 0
    height: int = 0
    bandwidth: int = 0          # bitrate in bps
    size_bytes: int = 0
    is_audio: bool = False
    format_id: str = ""         # yt-dlp format_id for precise format selection


@dataclass
class DownloadTask:
    """Represents a single download task."""
    platform: str
    video_info: VideoInfo
    video_stream: Optional[MediaStream] = None
    audio_stream: Optional[MediaStream] = None  # separate audio for Bilibili DASH
    output_path: str = ""
    filename: str = ""
    total_size: int = 0
    downloaded: int = 0
    status: str = "pending"     # pending, downloading, paused, completed, error
    error_msg: str = ""
    page_index: int = 0          # page/episode index for multi-P videos
    page_label: str = ""         # e.g. "P01" for use in filenames
    audio_only: bool = False     # True = extract audio only (MP3 output)


class BasePlatform(ABC):
    """Abstract platform adapter. Each platform (Bilibili) implements this."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Platform display name."""
        ...

    @abstractmethod
    async def parse_url(self, url: str) -> VideoInfo:
        """
        Parse a video URL and return basic video info.
        Must detect the video ID and fetch metadata.
        """
        ...

    @abstractmethod
    async def get_streams(self, video_info: VideoInfo, page_index: int = 0) -> list[MediaStream]:
        """
        Get all available media streams for a video.
        Returns list of video streams and audio streams.
        """
        ...

    async def resolve_download(self, video_info: VideoInfo, quality: VideoQuality,
                               page_index: int = 0, page_label: str = "") -> DownloadTask:
        """
        Create a download task by selecting the best stream matching requested quality.
        """
        streams = await self.get_streams(video_info, page_index=page_index)

        # Filter video streams
        video_streams = [s for s in streams if not s.is_audio]

        if not video_streams:
            raise ValueError(f"No video streams found for {video_info.title}")

        # Select best match for requested quality
        selected = self._select_quality(video_streams, quality)

        # For DASH streams (separate video+audio), find matching audio
        audio_stream = None
        if selected and selected.codecs:  # likely DASH format
            audio_streams = [s for s in streams if s.is_audio]
            if audio_streams:
                # Pick the highest quality audio
                audio_stream = max(audio_streams, key=lambda s: s.bandwidth)

        task = DownloadTask(
            platform=self.name,
            video_info=video_info,
            video_stream=selected,
            audio_stream=audio_stream,
            page_index=page_index,
            page_label=page_label,
        )
        return task

    def _select_quality(self, streams: list[MediaStream], preferred: VideoQuality) -> Optional[MediaStream]:
        """Select the stream closest to the preferred quality."""
        if not streams:
            return None

        # Quality ordering for comparison
        quality_order = {
            VideoQuality.UNKNOWN: 0,
            VideoQuality.Q_144P: 1,
            VideoQuality.Q_240P: 2,
            VideoQuality.Q_360P: 3,
            VideoQuality.Q_480P: 4,
            VideoQuality.Q_540P: 5,
            VideoQuality.Q_720P: 6,
            VideoQuality.Q_1080P: 7,
            VideoQuality.Q_1080P_HIGH_BITRATE: 8,
            VideoQuality.Q_1440P: 9,
            VideoQuality.Q_2160P: 10,
            VideoQuality.Q_4320P: 11,
        }

        target = quality_order.get(preferred, 0)
        best = streams[0]

        for s in streams:
            current = quality_order.get(s.quality, 0)
            best_quality = quality_order.get(best.quality, 0)
            if abs(current - target) < abs(best_quality - target):
                best = s
            elif current == best_quality and s.bandwidth > best.bandwidth:
                best = s

        return best
