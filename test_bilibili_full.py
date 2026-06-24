"""
Comprehensive Bilibili platform adapter test.
Tests the full parse → get_streams → resolve_download pipeline
with the real URL the user reported: BV16ooQBsERA.
"""
import sys, os, time, asyncio, threading
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["PYTHONIOENCODING"] = "utf-8"

TEST_URL = "https://www.bilibili.com/video/BV16ooQBsERA/?spm_id_from=333.1007.tianma.1-1-1.click"

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}" + (f" — {detail}" if detail else ""))


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ── 1. Direct API call (like parse_url does internally) ──
section("1. Direct bilibili-api calls")

async def test_direct_api():
    from bilibili_api import video as bili_video
    import re

    bv_match = re.search(r'BV\w{10,12}', TEST_URL, re.IGNORECASE)
    bvid = bv_match.group(0)
    check("BVID extraction", bvid == "BV16ooQBsERA", f"got {bvid}")

    v = bili_video.Video(bvid=bvid)

    t0 = time.time()
    info = await v.get_info()
    t_info = time.time() - t0
    check("get_info() < 5s", t_info < 5.0, f"took {t_info:.2f}s")
    check("Title non-empty", bool(info.get("title")), f"title={info.get('title')}")
    check("Has duration > 0", info.get("duration", 0) > 0, f"duration={info.get('duration')}")
    check("Has cover pic", bool(info.get("pic")), f"pic={info.get('pic','')[:60]}")
    check("Has owner", bool(info.get("owner")), f"owner={info.get('owner',{})}")

    t0 = time.time()
    url_data = await v.get_download_url(page_index=0)
    t_durl = time.time() - t0
    check("get_download_url() < 5s", t_durl < 5.0, f"took {t_durl:.2f}s")
    check("Has DASH data", "dash" in url_data, f"keys={list(url_data.keys())}")
    check("Has video streams in DASH", len(url_data.get("dash", {}).get("video", [])) > 0,
          f"video_count={len(url_data.get('dash',{}).get('video',[]))}")
    check("Has audio streams in DASH", len(url_data.get("dash", {}).get("audio", [])) > 0,
          f"audio_count={len(url_data.get('dash',{}).get('audio',[]))}")

    return info, url_data

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
info, url_data = loop.run_until_complete(test_direct_api())
loop.close()


# ── 2. Platform adapter parse_url ──
section("2. BilibiliPlatform.parse_url()")

async def test_platform_parse():
    from app.platforms.bilibili import BilibiliPlatform
    plat = BilibiliPlatform()

    t0 = time.time()
    vinfo = await plat.parse_url(TEST_URL)
    elapsed = time.time() - t0
    check("parse_url() < 10s", elapsed < 10.0, f"took {elapsed:.2f}s")
    check("video_id = BV16ooQBsERA", vinfo.video_id == "BV16ooQBsERA")
    check("title non-empty", bool(vinfo.title))
    check("duration > 0", vinfo.duration > 0, f"{vinfo.duration}s")
    check("cover_url non-empty", bool(vinfo.cover_url))
    check("author_name non-empty", bool(vinfo.author_name), f"author={vinfo.author_name}")
    check("platform = bilibili", vinfo.platform == "bilibili")
    check("available_qualities not empty", len(vinfo.available_qualities) > 0,
          f"qualities={[q.value for q in vinfo.available_qualities]}")

    return plat, vinfo

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
plat, vinfo = loop.run_until_complete(test_platform_parse())
loop.close()


# ── 3. Platform adapter get_streams ──
section("3. BilibiliPlatform.get_streams()")

async def test_get_streams():
    t0 = time.time()
    streams = await plat.get_streams(vinfo)
    elapsed = time.time() - t0
    check("get_streams() < 5s", elapsed < 5.0, f"took {elapsed:.2f}s")
    check("Has streams", len(streams) > 0, f"count={len(streams)}")

    video_streams = [s for s in streams if not s.is_audio]
    audio_streams = [s for s in streams if s.is_audio]
    check("Has video streams", len(video_streams) > 0, f"count={len(video_streams)}")
    check("Has audio streams", len(audio_streams) > 0, f"count={len(audio_streams)}")

    for s in video_streams[:3]:
        check("Stream has URL", bool(s.url), f"quality={s.quality.value} url={s.url[:40]}...")
        check(f"Stream quality != UNKNOWN", s.quality.value != "unknown",
              f"quality={s.quality.value}")

    return streams

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
streams = loop.run_until_complete(test_get_streams())
loop.close()


# ── 4. resolve_download (used by DownloadResolveWorker) ──
section("4. BasePlatform.resolve_download()")

async def test_resolve():
    from app.platforms.base import VideoQuality
    for q in [VideoQuality.Q_480P, VideoQuality.Q_360P, VideoQuality.UNKNOWN]:
        task = await plat.resolve_download(vinfo, q)
        check(f"resolve_download({q.value}) has video_stream",
              task.video_stream is not None)
        check(f"resolve_download({q.value}) has URL",
              bool(task.video_stream and task.video_stream.url))

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.run_until_complete(test_resolve())
loop.close()


# ── 5. Thread safety (simulates QThread ParseWorker) ──
section("5. Thread-safety (ParseWorker simulation)")

class ParseThread(threading.Thread):
    def __init__(self):
        super().__init__()
        self.error = None
        self.done = False

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(plat.parse_url(TEST_URL))
            loop.close()
            self.done = True
        except Exception as e:
            self.error = e

t = ParseThread()
t0 = time.time()
t.start()
t.join(timeout=20)
elapsed = time.time() - t0
check("Thread completes within 20s", t.done, f"took {elapsed:.2f}s error={t.error}")
if t.error:
    check("No thread error", False, str(t.error))
elif t.done:
    check("Thread parse OK", True)


# ── 6. Cover URL accessibility ──
section("6. Cover image URL accessibility")

if vinfo.cover_url:
    import httpx
    t0 = time.time()
    try:
        resp = httpx.get(vinfo.cover_url, timeout=10.0, follow_redirects=True)
        elapsed = time.time() - t0
        check("Cover URL reachable", resp.status_code == 200,
              f"status={resp.status_code} size={len(resp.content)} took={elapsed:.2f}s")
        check("Cover image has content", len(resp.content) > 1000,
              f"got {len(resp.content)} bytes")
    except Exception as e:
        check("Cover URL accessible", False, str(e))
else:
    check("Cover URL available", False, "No cover_url in VideoInfo")


# ── Summary ──
section(f"RESULTS: {passed} passed, {failed} failed")
if failed == 0:
    print("ALL CHECKS PASSED ✓")
else:
    print(f"SOME CHECKS FAILED ✗")
