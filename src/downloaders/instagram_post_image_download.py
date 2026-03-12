"""Instagram Post image download — single images, image carousels, HTTP fallback."""

import io

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

_MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/16.6 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


async def download_post_image(url: str, info: dict) -> DownloadResult:
    """Download a single image post using yt-dlp metadata."""
    return await download_single_image(url, info)


async def download_post_image_via_http(url: str) -> DownloadResult:
    """Download post images via HTTP when yt-dlp can't handle them."""
    return await download_post_via_http(url)


async def download_image_carousel(url: str, info: dict) -> DownloadResult:
    """Download a carousel of images into memory."""
    entries = info.get("entries", [])
    if not entries:
        raise DownloadError(
            "Carousel has no entries", platform="instagram"
        )

    logger.info(f"[Instagram Image] Downloading carousel with {len(entries)} images")

    buffers: list[io.BytesIO] = []
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, headers=_MOBILE_HEADERS
    ) as client:
        for i, entry in enumerate(entries):
            img_url = get_best_image_url(entry)
            if img_url:
                try:
                    resp = await client.get(img_url)
                    resp.raise_for_status()
                    buf = io.BytesIO(resp.content)
                    buf.seek(0)
                    buffers.append(buf)
                    logger.debug(
                        f"[Instagram Image] Carousel item {i+1}: "
                        f"{len(resp.content)} bytes"
                    )
                except Exception as e:
                    logger.warning(
                        f"[Instagram Image] Failed carousel image {i+1}: {e}"
                    )

    if not buffers:
        raise DownloadError(
            "Failed to download any carousel images",
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
            filename="instagram_image.jpg",
            file_size=first_size,
            media_type=MediaType.IMAGE,
            caption=caption,
        )

    return DownloadResult(
        buffer=first,
        filename="instagram_carousel_1.jpg",
        file_size=first_size,
        media_type=MediaType.IMAGES,
        caption=caption,
        extra_buffers=buffers[1:],
    )
