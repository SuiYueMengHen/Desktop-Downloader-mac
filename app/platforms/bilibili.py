"""
Bilibili platform adapter.
  - Parse: bilibili-api-python (reliable Bilibili API integration)
  - Download: yt-dlp (handles DASH merging, progress, retries)
"""
import re
import sys
import asyncio
import traceback
from typing import Optional

import yt_dlp
from bilibili_api import video as bili_video
from bilibili_api import user as bili_user
from bilibili_api import channel_series
from bilibili_api import search as bili_search
from bilibili_api import Credential
from bilibili_api.utils.utils import get_api
from bilibili_api.utils.network import Api
from bilibili_api.exceptions.NetworkException import NetworkException

from app.platforms.base import BasePlatform, VideoInfo, VideoQuality, MediaStream
from app.cookie_manager import CookieManager


def _log_error(msg: str, exc: Exception = None):
    """Print error to terminal (stderr) for debugging."""
    print(f"[ERROR] {msg}", file=sys.stderr, flush=True)
    if exc:
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)


BILIBILI_QUALITIES = {
    # qn → VideoQuality mapping based on official bilibili API
    6:   VideoQuality.Q_240P,   # 240P 极速
    16:  VideoQuality.Q_360P,   # 360P 流畅
    32:  VideoQuality.Q_480P,   # 480P 清晰
    48:  VideoQuality.Q_720P,   # 720P (older encode)
    64:  VideoQuality.Q_720P,   # 720P 高清
    74:  VideoQuality.Q_720P,   # 720P 60帧
    80:  VideoQuality.Q_1080P,  # 1080P 高清
    84:  VideoQuality.Q_1080P,  # 1080P 60帧
    96:  VideoQuality.Q_1080P,  # 1080P 高帧率
    112: VideoQuality.Q_1080P_HIGH_BITRATE,  # 1080P 高码率
    116: VideoQuality.Q_1080P,  # 1080P 60帧 (AV1/HEVC variant)
    120: VideoQuality.Q_2160P,  # 4K 超高清
    125: VideoQuality.Q_2160P,  # 4K HDR
    126: VideoQuality.Q_2160P,  # 4K 超高清 (high bitrate)
    127: VideoQuality.Q_4320P,  # 8K 超高清
    302: VideoQuality.Q_720P,   # 720P HEVC
    303: VideoQuality.Q_1080P,  # 1080P HEVC
}


def _height_to_quality(height: int) -> VideoQuality:
    mapping = [
        (144, VideoQuality.Q_144P), (240, VideoQuality.Q_240P),
        (360, VideoQuality.Q_360P), (480, VideoQuality.Q_480P),
        (540, VideoQuality.Q_540P), (720, VideoQuality.Q_720P),
        (1080, VideoQuality.Q_1080P), (1440, VideoQuality.Q_1440P),
        (2160, VideoQuality.Q_2160P), (4320, VideoQuality.Q_4320P),
    ]
    for h, q in mapping:
        if height <= h:
            return q
    return VideoQuality.Q_4320P


def extract_bvid(url: str) -> Optional[str]:
    bv = re.search(r'BV\w{10,12}', url, re.IGNORECASE)
    if bv: return bv.group(0)
    av = re.search(r'av(\d+)', url, re.IGNORECASE)
    if av: return f"av{av.group(1)}"
    return None


def extract_uid(url: str) -> Optional[int]:
    """Extract numeric UID from Bilibili space URL."""
    m = re.search(r'space\.bilibili\.com/(\d+)', url)
    if m: return int(m.group(1))
    m = re.search(r'bilibili\.com/(\d+)', url)
    if m: return int(m.group(1))
    return None


def extract_series_id(url: str) -> Optional[int]:
    """Extract collection/series ID from Bilibili collection URL.
    URL format: https://space.bilibili.com/{uid}/lists/{series_id}
    """
    m = re.search(r'/lists/(\d+)', url)
    if m:
        return int(m.group(1))
    return None


class BilibiliPlatform(BasePlatform):
    @property
    def name(self) -> str: return "bilibili"

    def __init__(self):
        self.cookie_manager = CookieManager()
        self._credential = self._build_credential()

    def _build_credential(self) -> Credential:
        sess = self.cookie_manager.bilibili_sessdata
        jct = self.cookie_manager.bilibili_bili_jct
        buvid = self.cookie_manager.bilibili_buvid3
        if sess and jct:
            return Credential(sessdata=sess, bili_jct=jct, buvid3=buvid or "")
        return Credential()

    def refresh_credential(self):
        """Rebuild credential from stored cookies (reload from config)."""
        self._credential = self._build_credential()

    async def validate_credential(self) -> bool:
        """Check if the current credential is still valid by making a
        lightweight API call. Returns True if valid, False if expired/invalid."""
        if not self._check_login():
            return False
        try:
            # get_user_info() requires valid login; use current user's UID
            # If credential is expired, this will raise an exception
            info = await bili_user.get_self_info(credential=self._credential)
            return info is not None
        except Exception as e:
            _log_error("凭证验证失败", e)
            return False

    def _check_login(self) -> bool:
        """Check if credentials are configured (does not verify validity)."""
        return bool(self.cookie_manager.bilibili_sessdata and
                    self.cookie_manager.bilibili_bili_jct)

    def _get_ydl_opts(self) -> dict:
        opts = {
            'quiet': True, 'no_warnings': True,
            'ffmpeg_location': self.cookie_manager.config.ffmpeg_location,
        }
        # Build Netscape cookie file for yt-dlp
        sess = self.cookie_manager.bilibili_sessdata
        jct = self.cookie_manager.bilibili_bili_jct
        buvid = self.cookie_manager.bilibili_buvid3
        if sess and jct:
            cookie_dir = self.cookie_manager.config.cookie_dir
            cookie_dir.mkdir(parents=True, exist_ok=True)
            cookie_path = cookie_dir / "bilibili_cookies.txt"
            lines = [
                "# Netscape HTTP Cookie File",
                ".bilibili.com\tTRUE\t/\tFALSE\t1735689600\tSESSDATA\t" + sess,
                ".bilibili.com\tTRUE\t/\tFALSE\t1735689600\tbili_jct\t" + jct,
                ".bilibili.com\tTRUE\t/\tFALSE\t1735689600\tbuvid3\t" + (buvid or ""),
            ]
            cookie_path.write_text("\n".join(lines), encoding="utf-8")
            opts['cookiefile'] = str(cookie_path)
        return opts

    async def parse_url(self, url: str) -> VideoInfo:
        bvid = extract_bvid(url)
        if not bvid:
            raise ValueError(f"无法解析Bilibili视频ID: {url}")

        v = bili_video.Video(bvid=bvid, credential=self._credential)
        info = await v.get_info()

        title = info.get("title", f"Video_{bvid}")
        duration = info.get("duration", 0) or 0
        cover = info.get("pic", "") or \
                (info.get("pic") or "")
        author = info.get("owner", {}).get("name", info.get("uploader", ""))
        author_uid = str(info.get("owner", {}).get("mid", info.get("uploader_id", "")))

        # Detect available qualities directly from DASH data
        qualities = [VideoQuality.UNKNOWN]
        try:
            url_data = await v.get_download_url(page_index=0)
            if "dash" in url_data:
                dash = url_data["dash"]
                seen_ids = set()
                for vs in dash.get("video", []):
                    qid = vs.get("id", 0)
                    if qid in seen_ids:
                        continue
                    seen_ids.add(qid)
                    q = BILIBILI_QUALITIES.get(qid, _height_to_quality(vs.get("height", 0)))
                    if q not in qualities and q != VideoQuality.UNKNOWN:
                        qualities.append(q)
        except Exception:
            pass

        # Detect multi-P (pages/parts)
        pages_raw = info.get("pages", [])
        total_pages = info.get("videos", 1) or 1
        pages = []
        for i, p in enumerate(pages_raw):
            pages.append({
                "page": i,  # 0-indexed
                "part": p.get("part", f"P{i+1:02d}"),
                "duration": p.get("duration", 0),
            })

        # Attach raw API data and webpage URL for yt-dlp download
        raw = dict(info)
        raw["webpage_url"] = f"https://www.bilibili.com/video/{bvid}"
        raw["pages"] = pages
        raw["total_pages"] = total_pages

        return VideoInfo(
            platform=self.name, video_id=bvid, title=title,
            description=(info.get("desc") or "")[:500],
            duration=duration, cover_url=cover,
            author_name=author, author_uid=author_uid,
            available_qualities=qualities,
            raw_data=raw,
        )

    async def get_streams(self, video_info: VideoInfo, page_index: int = 0) -> list[MediaStream]:
        """Get available DASH streams via bilibili-api."""
        streams = []
        bvid = video_info.video_id
        try:
            v = bili_video.Video(bvid=bvid, credential=self._credential)
            url_data = await v.get_download_url(page_index=page_index)

            if "dash" in url_data:
                dash = url_data["dash"]
                # Video streams — prefer baseUrl, fall back to backup_url
                for vs in dash.get("video", []):
                    qid = vs.get("id", 0)
                    quality = BILIBILI_QUALITIES.get(qid, VideoQuality.UNKNOWN)
                    url = vs.get("baseUrl") or vs.get("base_url", "")
                    if not url and vs.get("backup_url"):
                        url = vs["backup_url"][0]
                    streams.append(MediaStream(
                        url=url, quality=quality,
                        mime_type=vs.get("mime_type", "video/mp4"),
                        codecs=vs.get("codecs", ""),
                        width=vs.get("width", 0), height=vs.get("height", 0),
                        bandwidth=vs.get("bandwidth", 0),
                        size_bytes=vs.get("size", 0), is_audio=False,
                    ))
                # Audio streams
                for au in dash.get("audio", []):
                    url = au.get("baseUrl") or au.get("base_url", "")
                    if not url and au.get("backup_url"):
                        url = au["backup_url"][0]
                    streams.append(MediaStream(
                        url=url, quality=VideoQuality.UNKNOWN,
                        mime_type=au.get("mime_type", "audio/mp4"),
                        bandwidth=au.get("bandwidth", 0), is_audio=True,
                    ))
            elif "durl" in url_data:
                for durl in url_data["durl"]:
                    streams.append(MediaStream(
                        url=durl["url"], quality=VideoQuality.UNKNOWN,
                        mime_type="video/mp4", is_audio=False,
                    ))
        except Exception as e:
            raise ValueError(f"获取Bilibili视频流失败: {e}")

        return streams

    def get_format_spec_for_quality(self, quality: VideoQuality) -> str:
        """Build yt-dlp format spec based on quality selection.
        Since yt-dlp's Bilibili extractor has issues, we use a generic approach
        or fallback to best quality."""
        h_map = {
            VideoQuality.UNKNOWN: 99999, VideoQuality.Q_144P: 144,
            VideoQuality.Q_240P: 240, VideoQuality.Q_360P: 360,
            VideoQuality.Q_480P: 480, VideoQuality.Q_540P: 540,
            VideoQuality.Q_720P: 720, VideoQuality.Q_1080P: 1080,
            VideoQuality.Q_1440P: 1440, VideoQuality.Q_2160P: 2160,
        }
        h = h_map.get(quality, 99999)
        if h >= 99999: return "bv*+ba/best"
        return f"bv*[height<={h}]+ba/best[height<={h}]"

    # ── Search methods ──

    async def search_videos(self, keyword: str, page: int = 1, page_size: int = 20) -> dict:
        """Search Bilibili videos by keyword.

        Returns dict with keys: videos (list), page, count, has_more
        Each video: bvid, title, cover, duration, play, author, author_uid, pubdate
        """
        try:
            # Use library's search_by_type (handles WBI signing internally, no credential needed)
            data = await bili_search.search_by_type(
                keyword=keyword,
                search_type=bili_search.SearchObjectType.VIDEO,
                page=page,
                page_size=page_size,
            )
        except Exception as e:
            _log_error(f"搜索请求失败: keyword={keyword}, page={page}", e)
            raise ValueError(f"搜索请求失败: {e}")

        results = data.get("result", [])
        total_count = data.get("numResults", 0) or data.get("total", 0)
        page_size_resp = data.get("pagesize", page_size)
        total_pages = max(1, (total_count + page_size_resp - 1) // page_size_resp)

        videos = []
        for v in results:
            bvid = v.get("bvid", "") or v.get("aid", "")
            title = v.get("title", "")
            # Strip HTML tags from title (bilibili search returns HTML-escaped titles)
            title = re.sub(r'<[^>]+>', '', title)
            cover = v.get("pic", "")
            # Fix protocol-relative URL (//i0.hdslb.com/... -> https://i0.hdslb.com/...)
            if cover and cover.startswith("//"):
                cover = "https:" + cover
            duration_str = v.get("duration", "0:00")
            duration = _parse_duration_str(duration_str)
            videos.append({
                "bvid": bvid,
                "aid": v.get("aid", 0),
                "title": title,
                "cover": cover,
                "duration": duration,
                "play": v.get("play", 0),
                "danmaku": v.get("video_review", v.get("danmaku", 0)),
                "author": v.get("author", ""),
                "author_uid": str(v.get("mid", 0)),
                "pubdate": v.get("pubdate", 0),
                "tag": v.get("tag", ""),
            })

        return {
            "videos": videos,
            "page": page,
            "count": total_count,
            "total_pages": total_pages,
            "has_more": page < total_pages,
        }

    async def search_uploaders(self, keyword: str, page: int = 1, page_size: int = 20) -> dict:
        """Search Bilibili uploaders (UP主) by keyword.

        Returns dict with keys: uploaders (list), page, count, has_more
        Each uploader: uid, name, sign, face, fans, videos, level
        """
        try:
            data = await bili_search.search_by_type(
                keyword=keyword,
                search_type=bili_search.SearchObjectType.USER,
                page=page,
                page_size=page_size,
            )
        except Exception as e:
            _log_error(f"UP主搜索请求失败: keyword={keyword}, page={page}", e)
            raise ValueError(f"UP主搜索请求失败: {e}")

        results = data.get("result", [])
        total_count = data.get("numResults", 0) or data.get("total", 0)
        page_size_resp = data.get("pagesize", page_size)
        total_pages = max(1, (total_count + page_size_resp - 1) // page_size_resp)

        uploaders = []
        for u in results:
            face = u.get("upic", "")
            if face and face.startswith("//"):
                face = "https:" + face
            uploaders.append({
                "uid": u.get("mid", 0),
                "name": u.get("uname", "未知"),
                "sign": u.get("usign", ""),
                "face": face,
                "fans": u.get("fans", 0),
                "videos": u.get("videos", 0),
                "level": u.get("level", 0),
            })

        return {
            "uploaders": uploaders,
            "page": page,
            "count": total_count,
            "total_pages": total_pages,
            "has_more": page < total_pages,
        }

    # ── Uploader (UP主) methods ──

    # ── Series / Collection methods ──

    async def get_series_info(self, series_id: int) -> dict:
        """Fetch collection/series metadata."""
        api_def = get_api('user')['channel_series']['season_info']
        resp = await Api(**api_def).update_params(**{"season_id": series_id}).result
        info = resp.get("info", {})
        upper = info.get("upper", {})
        cnt = info.get("cnt_info", {})
        return {
            "series_id": series_id,
            "name": info.get("title", "未命名合集"),
            "cover": info.get("cover", ""),
            "intro": info.get("intro", ""),
            "media_count": info.get("media_count", 0),
            "upper_mid": upper.get("mid", 0),
            "upper_name": upper.get("name", ""),
            "play": cnt.get("play", 0),
            "danmaku": cnt.get("danmaku", 0),
            "collect": cnt.get("collect", 0),
        }

    async def get_series_videos(self, series_id: int, page: int = 1, page_size: int = 100) -> dict:
        """Fetch videos in a collection/series.
        Returns dict with keys: videos (list), page, has_more, count
        Each video: bvid, title, cover, duration, play, danmaku, pubdate, aid
        """
        cs = channel_series.ChannelSeries(
            id_=series_id,
            type_=channel_series.ChannelSeriesType.SEASON,
            credential=self._credential,
        )
        data = await cs.get_videos(pn=page, ps=page_size)
        archives = data.get("archives", [])
        page_info = data.get("page", {})
        total = page_info.get("total", page_info.get("count", len(archives)))
        results = []
        for v in archives:
            stat = v.get("stat", {})
            results.append({
                "bvid": v.get("bvid", ""),
                "aid": v.get("aid", 0),
                "title": v.get("title", "无标题"),
                "cover": v.get("pic", ""),
                "duration": v.get("duration", 0),
                "play": stat.get("view", 0),
                "danmaku": stat.get("danmaku", 0),
                "pubdate": v.get("pubdate", 0),
            })
        current_page = page_info.get("num", page)
        current_size = page_info.get("size", page_size)
        return {
            "videos": results,
            "page": current_page,
            "count": total,
            "has_more": (current_page * current_size) < total,
        }

    async def _api_retry(self, fn, *args, max_retries: int = 3, base_delay: float = 1.0, **kwargs):
        """Call an async API function with retry on 412 errors."""
        last_exc = None
        for attempt in range(max_retries):
            try:
                return await fn(*args, **kwargs)
            except NetworkException as e:
                last_exc = e
                if e.status == 412 and attempt < max_retries - 1:
                    await asyncio.sleep(base_delay * (attempt + 1))
                    continue
                raise
        raise last_exc

    async def get_uploader_info(self, uid: int) -> dict:
        """Fetch uploader profile info via bilibili-api.
        Uses Api directly to bypass w_webid requirement (get_access_id)
        which is fragile and often fails."""
        # Fetch user info directly via Api (api_def already has wbi=true, don't pass wbi again)
        try:
            api_def = get_api('user')['info']['info']
            info = await Api(**api_def, credential=self._credential).update_params(mid=uid).result
        except Exception as e:
            _log_error(f"获取UP主信息失败: uid={uid}", e)
            raise Exception(f"获取UP主信息失败: {e}")

        # Fetch relation info (optional, doesn't need w_webid)
        try:
            u = bili_user.User(uid, credential=self._credential)
            rel = await u.get_relation_info()
        except Exception as e:
            _log_error(f"获取UP主关系信息失败(非致命): uid={uid}", e)
            rel = {}

        # Fetch video count (optional, api_def already has wbi=true)
        vcount = 0
        try:
            vapi = get_api('user')['info']['video']
            vresp = await Api(**vapi, credential=self._credential).update_params(
                mid=uid, ps=1, pn=1, tid=0, keyword="", order="pubdate",
                order_avoided=True, platform="web",
            ).result
            vcount = vresp.get("page", {}).get("count", 0)
        except Exception as e:
            _log_error(f"获取UP主视频数量失败(非致命): uid={uid}", e)

        face = info.get("face", "")
        if face and face.startswith("//"):
            face = "https:" + face
        return {
            "uid": uid,
            "name": info.get("name", "未知"),
            "face": face,
            "sign": info.get("sign", ""),
            "level": info.get("level", 0),
            "video_count": vcount,
            "follower": rel.get("follower", 0),
            "following": rel.get("following", 0),
        }

    async def get_uploader_videos(self, uid: int, page: int = 1, page_size: int = 30) -> dict:
        """Fetch paginated video list from an uploader.
        Uses Api directly to bypass w_webid requirement."""
        try:
            # api_def already has wbi=true, don't pass wbi again
            api_def = get_api('user')['info']['video']
            resp = await Api(**api_def, credential=self._credential).update_params(
                mid=uid, ps=page_size, pn=page, tid=0, keyword="",
                order="pubdate", order_avoided=True, platform="web",
            ).result
        except Exception as e:
            _log_error(f"获取UP主视频列表失败: uid={uid}, page={page}", e)
            raise Exception(f"获取UP主视频列表失败: {e}")

        lst = resp.get("list", {})
        vlist = lst.get("vlist", [])
        page_info = resp.get("page", {})
        total = page_info.get("count", 0)
        results = []
        for v in vlist:
            dur_str = v.get("length", "0")
            duration = _parse_duration_str(dur_str)
            cover = v.get("pic", "")
            if cover and cover.startswith("//"):
                cover = "https:" + cover
            results.append({
                "bvid": v.get("bvid", ""),
                "title": v.get("title", "无标题"),
                "cover": cover,
                "duration": duration,
                "play": v.get("play", 0),
                "danmaku": v.get("video_review", v.get("danmaku", 0)),
                "pubdate": v.get("created", 0),
                "aid": v.get("aid", 0),
            })
        return {
            "videos": results,
            "page": page,
            "count": total,
            "has_more": (page * page_size) < total,
        }


def _parse_duration_str(s: str) -> int:
    """Convert duration string like '18:29' or '1:12:30' to seconds."""
    if not s:
        return 0
    try:
        parts = [int(x) for x in s.split(":")]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        elif len(parts) == 2:
            return parts[0] * 60 + parts[1]
        return parts[0] if parts else 0
    except (ValueError, IndexError):
        return 0
