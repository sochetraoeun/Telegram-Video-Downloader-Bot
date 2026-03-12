"""Instagram Post video download — Reels, single videos, video carousels."""

import io
import os

import httpx
from loguru import logger

from src.config.settings import settings
from src.downloaders.base_downloader import (
    DownloadResult,
    DownloadError,
    MediaType,
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
    """Return empty list — no cookies configured."""
    return []


def _get_cookies_args(_url: str) -> list[str]:
    """Return --cookies args when configured. Reels need them on server IPs."""
    path = settings.instagram_cookies_file
    if not path:
        return []
    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        logger.warning(f"[Instagram Video] Cookies file not found: {abs_path}")
        return []
    return ["--cookies", abs_path]


def _cookies_fn(url: str) -> list[str]:
    """Use cookies when configured."""
    return _get_cookies_args(url)


async def download_post_video(url: str, info: dict) -> DownloadResult:
    """Download a single Reel or video post."""
    return await download_video(url, info, _cookies_fn)


async def download_video_carousel(url: str, info: dict) -> DownloadResult:
    """Download a carousel of videos into memory."""
    entries = info.get("entries", [])
    if not entries:
        raise DownloadError(
            "Carousel has no entries", platform="instagram"
        )

    logger.info(f"[Instagram Video] Downloading carousel with {len(entries)} videos")

    buffers: list[io.BytesIO] = []
    for i, entry in enumerate(entries):
        entry_url = entry.get("webpage_url") or entry.get("url") or url
        try:
            video_buf = await download_video_bytes(
                entry_url, _cookies_fn
            )
            buffers.append(video_buf)
            logger.debug(f"[Instagram Video] Carousel item {i+1}: video")
        except Exception as e:
            logger.warning(
                f"[Instagram Video] Failed carousel video {i+1}: {e}"
            )

    if not buffers:
        raise DownloadError(
            "Failed to download any carousel videos",
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

    if len(buffers) == 1:
        return DownloadResult(
            buffer=first,
            filename="instagram_video.mp4",
            file_size=first_size,
            media_type=MediaType.VIDEO,
            caption=caption,
        )

    return DownloadResult(
        buffer=first,
        filename="instagram_carousel_1.mp4",
        file_size=first_size,
        media_type=MediaType.VIDEO,
        caption=caption,
        extra_buffers=buffers[1:],
    )
