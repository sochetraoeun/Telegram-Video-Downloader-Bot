"""Instagram Post/Reel download — Reels and Posts only, no cookies required."""

import io
import asyncio
import json
import re

import httpx
from loguru import logger

from src.downloaders.base_downloader import (
    DownloadResult,
    DownloadError,
    MediaType,
)
from src.downloaders.instagram_image_download import (
    download_single_image,
    download_post_via_http,
    get_best_image_url,
)
from src.downloaders.instagram_video_download import (
    download_video,
    download_video_bytes,
)

_MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/16.6 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _no_cookies(_url: str) -> list[str]:
    """Return empty list — posts/reels do not use cookies."""
    return []


def _is_carousel(info: dict) -> bool:
    if info.get("_type") == "playlist" and info.get("entries"):
        return len(info["entries"]) > 1
    return False


def _is_image_post(info: dict) -> bool:
    ext = info.get("ext", "")
    vcodec = info.get("vcodec", "none")
    formats = info.get("formats", [])

    if ext in ("mp4", "webm", "mkv", "mov", "flv"):
        logger.debug(f"[Instagram Post] Not image: video ext={ext}")
        return False
    if vcodec not in ("none", None, ""):
        logger.debug(f"[Instagram Post] Not image: vcodec={vcodec}")
        return False
    video_formats = [
        f for f in formats
        if f.get("vcodec", "none") not in ("none", None, "")
    ]
    if video_formats:
        logger.debug(
            f"[Instagram Post] Not image: {len(video_formats)} video format(s) found"
        )
        return False
    audio_only_formats = [
        f for f in formats
        if f.get("acodec", "none") not in ("none", None, "")
    ]
    if (
        audio_only_formats
        and not video_formats
        and ext not in ("jpg", "jpeg", "png", "webp")
    ):
        logger.debug("[Instagram Post] Not image: has audio formats, likely a video")
        return False
    if ext in ("jpg", "jpeg", "png", "webp"):
        logger.debug(f"[Instagram Post] Detected image: ext={ext}")
        return True
    logger.debug(f"[Instagram Post] Not image: ext={ext}, treating as video")
    return False


async def _extract_info(url: str) -> dict | None:
    """Extract metadata with yt-dlp --dump-json. No cookies."""
    try:
        args = [
            "yt-dlp",
            "--no-warnings",
            "--no-check-certificates",
            "--dump-json",
            "--quiet",
        ]
        args.append(url)

        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=30
        )

        if process.returncode != 0:
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            logger.warning(f"[Instagram Post] yt-dlp returned error: {error_msg}")
            return None

        raw = stdout.decode().strip()
        if not raw:
            return None

        lines = raw.split("\n")
        if len(lines) > 1:
            entries = [json.loads(line) for line in lines if line.strip()]
            return {
                "_type": "playlist",
                "entries": entries,
                "title": entries[0].get("title") if entries else None,
            }
        return json.loads(lines[0])

    except json.JSONDecodeError:
        logger.warning("[Instagram Post] yt-dlp output was not valid JSON")
        return None
    except asyncio.TimeoutError:
        raise DownloadError(
            "Info extraction timed out (>30s)",
            platform="instagram",
        )
    except DownloadError:
        raise
    except Exception as e:
        raise DownloadError(
            f"Info extraction failed: {e}",
            platform="instagram",
        )


async def _download_carousel(url: str, info: dict) -> DownloadResult:
    """Download a carousel post (multiple images/videos) into memory."""
    entries = info.get("entries", [])
    if not entries:
        raise DownloadError(
            "Carousel has no entries", platform="instagram"
        )

    logger.info(f"[Instagram Post] Downloading carousel with {len(entries)} items")

    buffers: list[io.BytesIO] = []
    media_types: list[MediaType] = []

    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, headers=_MOBILE_HEADERS
    ) as client:
        for i, entry in enumerate(entries):
            ext = entry.get("ext", "")
            is_image = ext in ("jpg", "jpeg", "png", "webp")

            if is_image:
                img_url = get_best_image_url(entry)
                if img_url:
                    try:
                        resp = await client.get(img_url)
                        resp.raise_for_status()
                        buf = io.BytesIO(resp.content)
                        buf.seek(0)
                        buffers.append(buf)
                        media_types.append(MediaType.IMAGE)
                        logger.debug(
                            f"[Instagram Post] Carousel item {i+1}: "
                            f"image ({len(resp.content)} bytes)"
                        )
                        continue
                    except Exception as e:
                        logger.warning(
                            f"[Instagram Post] Failed carousel image {i+1}: {e}"
                        )

            entry_url = entry.get("webpage_url") or entry.get("url") or url
            try:
                video_buf = await download_video_bytes(
                    entry_url, _no_cookies
                )
                buffers.append(video_buf)
                media_types.append(MediaType.VIDEO)
                logger.debug(f"[Instagram Post] Carousel item {i+1}: video")
            except Exception as e:
                logger.warning(
                    f"[Instagram Post] Failed carousel video {i+1}: {e}"
                )

    if not buffers:
        raise DownloadError(
            "Failed to download any carousel items",
            platform="instagram",
        )

    caption = info.get("title") or (
        entries[0].get("title") if entries else None
    )
    if caption == "NA":
        caption = None

    first = buffers[0]
    first_size = first.getbuffer().nbytes
    first.seek(0)

    all_images = all(mt == MediaType.IMAGE for mt in media_types)

    if len(buffers) == 1:
        return DownloadResult(
            buffer=first,
            filename="instagram_image.jpg"
            if all_images
            else "instagram_video.mp4",
            file_size=first_size,
            media_type=media_types[0],
            caption=caption,
        )

    return DownloadResult(
        buffer=first,
        filename="instagram_carousel_1.jpg"
        if all_images
        else "instagram_carousel_1",
        file_size=first_size,
        media_type=MediaType.IMAGES,
        caption=caption,
        extra_buffers=buffers[1:],
    )


async def download_post(url: str) -> DownloadResult:
    """Download an Instagram Reel or Post. No cookies required."""
    logger.info(f"[Instagram Post] Downloading: {url}")

    info = await _extract_info(url)

    if info is not None:
        logger.info(
            f"[Instagram Post] yt-dlp returned info: ext={info.get('ext')}, "
            f"vcodec={info.get('vcodec', 'N/A')}, "
            f"formats={len(info.get('formats', []))}, "
            f"type={info.get('_type', 'single')}"
        )

        if _is_carousel(info):
            return await _download_carousel(url, info)

        if _is_image_post(info):
            return await download_single_image(url, info)

        return await download_video(url, info, _no_cookies)

    is_reel = bool(re.search(r"instagram\.com/reels?/", url, re.IGNORECASE))
    if is_reel:
        logger.warning("[Instagram Post] yt-dlp failed for reel")
        raise DownloadError(
            "Could not extract reel video data",
            platform="instagram",
            retryable=True,
        )

    logger.info(
        "[Instagram Post] yt-dlp returned no data, trying HTTP fallback for images"
    )
    return await download_post_via_http(url)
