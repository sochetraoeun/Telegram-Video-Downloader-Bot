"""Instagram Story download — Stories only, requires cookies."""

import io
import os
import asyncio
import json
import re
from urllib.parse import urlparse, urlunparse

import httpx
from loguru import logger

from src.config.settings import settings
from src.downloaders.base_downloader import (
    DownloadResult,
    DownloadError,
    MediaType,
)
from src.downloaders.instagram_image_download import (
    download_single_image,
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

_STORY_PATTERN = re.compile(
    r"https?://(www\.)?instagram\.com/stories/.+", re.IGNORECASE
)


def _get_cookies_args() -> list[str]:
    """Return --cookies args for yt-dlp. Stories require cookies."""
    path = settings.instagram_cookies_file
    if not path:
        return []
    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        logger.warning(f"[Instagram Story] Cookies file not found: {abs_path}")
        return []
    return ["--cookies", abs_path]


def _normalize_story_url(url: str) -> str:
    """Strip query params from story URLs — some can cause yt-dlp to fail."""
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _is_carousel(info: dict) -> bool:
    if info.get("_type") == "playlist" and info.get("entries"):
        return len(info["entries"]) > 1
    return False


def _is_image_post(info: dict) -> bool:
    ext = info.get("ext", "")
    vcodec = info.get("vcodec", "none")
    formats = info.get("formats", [])

    if ext in ("mp4", "webm", "mkv", "mov", "flv"):
        return False
    if vcodec not in ("none", None, ""):
        return False
    video_formats = [
        f for f in formats
        if f.get("vcodec", "none") not in ("none", None, "")
    ]
    if video_formats:
        return False
    if ext in ("jpg", "jpeg", "png", "webp"):
        return True
    return False


async def _extract_info(url: str) -> dict | None:
    """Extract metadata with yt-dlp --dump-json. Uses cookies."""
    try:
        args = [
            "yt-dlp",
            "--no-warnings",
            "--no-check-certificates",
            "--dump-json",
            "--quiet",
        ]
        args.extend(_get_cookies_args())
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
            logger.warning(f"[Instagram Story] yt-dlp error: {error_msg}")
            err_lower = error_msg.lower()
            if "unreachable" in err_lower:
                raise DownloadError(
                    "Story could not be reached — it may have expired (stories last 24h) or the account may be private.",
                    platform="instagram",
                    retryable=False,
                )
            if "login" in err_lower or "cookie" in err_lower:
                raise DownloadError(
                    "Instagram session expired. Please export fresh cookies and update the cookies file.",
                    platform="instagram",
                    retryable=False,
                )
            raise DownloadError(
                f"Story download failed: {error_msg[:200]}",
                platform="instagram",
                retryable=False,
            )

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
        logger.warning("[Instagram Story] yt-dlp output was not valid JSON")
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
    """Download a story carousel (multiple slides) into memory."""
    entries = info.get("entries", [])
    if not entries:
        raise DownloadError(
            "Carousel has no entries", platform="instagram"
        )

    logger.info(f"[Instagram Story] Downloading carousel with {len(entries)} items")

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
                        continue
                    except Exception as e:
                        logger.warning(f"[Instagram Story] Failed carousel image {i+1}: {e}")

            entry_url = entry.get("webpage_url") or entry.get("url") or url
            try:
                video_buf = await download_video_bytes(
                    entry_url, lambda _: _get_cookies_args()
                )
                buffers.append(video_buf)
                media_types.append(MediaType.VIDEO)
            except Exception as e:
                logger.warning(f"[Instagram Story] Failed carousel video {i+1}: {e}")

    if not buffers:
        raise DownloadError(
            "Failed to download any carousel items",
            platform="instagram",
        )

    caption = info.get("title") or (entries[0].get("title") if entries else None)
    if caption == "NA":
        caption = None

    first = buffers[0]
    first_size = first.getbuffer().nbytes
    first.seek(0)

    all_images = all(mt == MediaType.IMAGE for mt in media_types)

    if len(buffers) == 1:
        return DownloadResult(
            buffer=first,
            filename="instagram_story.jpg" if all_images else "instagram_story.mp4",
            file_size=first_size,
            media_type=media_types[0],
            caption=caption,
        )

    return DownloadResult(
        buffer=first,
        filename="instagram_story_1.jpg" if all_images else "instagram_story_1",
        file_size=first_size,
        media_type=MediaType.IMAGES,
        caption=caption,
        extra_buffers=buffers[1:],
    )


async def download_story(url: str) -> DownloadResult:
    """Download an Instagram Story. Requires cookies to be configured."""
    url = _normalize_story_url(url)
    logger.info(f"[Instagram Story] Downloading: {url}")

    if not _get_cookies_args():
        raise DownloadError(
            "Instagram Stories require login. Add INSTAGRAM_COOKIES_BASE64 or INSTAGRAM_COOKIES_FILE. See deploy.md.",
            platform="instagram",
            retryable=False,
        )

    info = await _extract_info(url)

    if info is None:
        raise DownloadError(
            "Could not fetch story — session may have expired. Please update the cookies file.",
            platform="instagram",
            retryable=False,
        )

    logger.info(
        f"[Instagram Story] yt-dlp returned info: ext={info.get('ext')}, "
        f"type={info.get('_type', 'single')}"
    )

    if _is_carousel(info):
        return await _download_carousel(url, info)

    if _is_image_post(info):
        return await download_single_image(url, info)

    return await download_video(url, info, lambda _: _get_cookies_args())
