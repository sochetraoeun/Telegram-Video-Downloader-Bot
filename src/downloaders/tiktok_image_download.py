"""TikTok image download logic — photomode slideshows, scrape fallback."""

import io
import re
import html as htmlmod

import httpx
from loguru import logger

from src.downloaders.base_downloader import (
    DownloadResult,
    DownloadError,
    MediaType,
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


def extract_photomode_urls(html: str) -> list[str]:
    """Extract unique photomode image URLs from TikTok page HTML."""
    decoded = html.replace(r"\u002F", "/").replace(r"\u0026", "&")

    pattern = (
        r"(https://p\d+-sign[^\s\"<>\\]+?"
        r"tplv-photomode-image\.jpeg"
        r"[^\s\"<>\\]*)"
    )
    raw_matches = re.findall(pattern, html)
    decoded_matches = re.findall(pattern, decoded)

    seen_hashes: set[str] = set()
    unique: list[str] = []

    for u in raw_matches + decoded_matches:
        clean = htmlmod.unescape(u)
        h = re.search(r"/([a-f0-9]{32})~", clean)
        if h and h.group(1) not in seen_hashes:
            seen_hashes.add(h.group(1))
            unique.append(clean)

    logger.info(f"[TikTok] Found {len(unique)} photomode image(s) in page")
    return unique


def extract_title_from_html(html: str) -> str | None:
    """Extract post title/caption from page HTML."""
    match = re.search(r"<title>([^<]+)</title>", html)
    if match:
        title = htmlmod.unescape(match.group(1)).strip()
        if title and title != "TikTok" and "Make Your Day" not in title:
            return title
    return None


def collect_image_urls(info: dict) -> list[str]:
    """Extract image URLs from yt-dlp metadata."""
    urls: list[str] = []

    if info.get("entries"):
        for entry in info["entries"]:
            url = entry.get("url")
            if url and entry.get("ext") in ("jpg", "jpeg", "png", "webp"):
                urls.append(url)

    if not urls:
        for fmt in info.get("formats", []):
            if fmt.get("format_note") == "Image" or fmt.get("ext") in (
                "jpg",
                "jpeg",
                "png",
                "webp",
            ):
                url = fmt.get("url")
                if url:
                    urls.append(url)

    return urls


async def download_images_from_info(
    url: str, info: dict
) -> DownloadResult:
    """Download images when yt-dlp metadata contains image URLs."""
    image_urls = collect_image_urls(info)
    if not image_urls:
        logger.warning(
            "[TikTok] yt-dlp metadata had no image URLs, falling back to scrape"
        )
        return await download_images_via_scrape(url)
    return await fetch_images(image_urls, info)


async def download_images_via_scrape(url: str) -> DownloadResult:
    """Fallback: scrape TikTok page HTML for photomode image URLs."""
    logger.info("[TikTok] Scraping page for image URLs")

    try:
        async with httpx.AsyncClient(
            timeout=20, follow_redirects=True, headers=_MOBILE_HEADERS
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as e:
        raise DownloadError(
            f"Failed to fetch TikTok page: {e}",
            platform="tiktok",
        )

    page = resp.text
    image_urls = extract_photomode_urls(page)

    if not image_urls:
        raise DownloadError(
            "No images found on this TikTok page",
            platform="tiktok",
            retryable=False,
        )

    caption = extract_title_from_html(page)
    return await fetch_images(image_urls, {"title": caption})


async def fetch_images(
    image_urls: list[str], info: dict
) -> DownloadResult:
    """Download image bytes from URLs into BytesIO buffers."""
    logger.info(f"[TikTok] Downloading {len(image_urls)} image(s)")

    buffers: list[io.BytesIO] = []
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, headers=_MOBILE_HEADERS
    ) as client:
        for i, img_url in enumerate(image_urls):
            try:
                resp = await client.get(img_url)
                resp.raise_for_status()
                buf = io.BytesIO(resp.content)
                buf.seek(0)
                buffers.append(buf)
                logger.debug(
                    f"[TikTok] Image {i+1}/{len(image_urls)}: "
                    f"{len(resp.content)} bytes"
                )
            except Exception as e:
                logger.warning(f"[TikTok] Failed to download image {i+1}: {e}")

    if not buffers:
        raise DownloadError(
            "Failed to download any images",
            platform="tiktok",
        )

    caption = info.get("title") or info.get("description")
    if caption == "NA":
        caption = None

    first = buffers[0]
    first_size = first.getbuffer().nbytes
    first.seek(0)

    if len(buffers) == 1:
        return DownloadResult(
            buffer=first,
            filename="tiktok_image.jpg",
            file_size=first_size,
            media_type=MediaType.IMAGE,
            caption=caption,
        )

    return DownloadResult(
        buffer=first,
        filename="tiktok_image_1.jpg",
        file_size=first_size,
        media_type=MediaType.IMAGES,
        caption=caption,
        extra_buffers=buffers[1:],
    )
