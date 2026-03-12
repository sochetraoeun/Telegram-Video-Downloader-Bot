"""Instagram image download logic — single images, carousel images, HTTP fallback."""

import io
import json
import re
import html as htmlmod

import httpx
from loguru import logger

from src.downloaders.base_downloader import DownloadResult, DownloadError, MediaType

_MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/16.6 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def extract_shortcode(url: str) -> str | None:
    """Extract the post shortcode from an Instagram URL."""
    match = re.search(r"instagram\.com/(?:p|reel|reels)/([A-Za-z0-9_-]+)", url)
    return match.group(1) if match else None


def get_best_image_url(info: dict) -> str | None:
    """Get the best quality image URL from metadata."""
    if info.get("url") and info.get("ext") in ("jpg", "jpeg", "png", "webp"):
        return info["url"]

    image_formats = [
        f for f in info.get("formats", [])
        if f.get("ext") in ("jpg", "jpeg", "png", "webp")
    ]
    if image_formats:
        best = max(
            image_formats,
            key=lambda f: f.get("width", 0) * f.get("height", 0),
        )
        return best.get("url")

    thumbnails = info.get("thumbnails", [])
    if thumbnails:
        best = max(
            thumbnails,
            key=lambda t: t.get("width", 0) * t.get("height", 0),
        )
        return best.get("url")

    return None


def _unescape_url(raw: str) -> str:
    return raw.replace("\\u0026", "&").replace("\\/", "/")


def _extract_json_object(text: str, start: int) -> str | None:
    """Extract a balanced {...} JSON object starting from a position in text."""
    idx = text.find("{", start)
    if idx == -1:
        return None
    depth = 0
    for i in range(idx, min(idx + 100000, len(text))):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[idx : i + 1]
    return None


def _extract_json_array(text: str, start: int) -> str | None:
    """Extract a balanced [...] JSON array starting from a position in text."""
    idx = text.find("[", start)
    if idx == -1:
        return None
    depth = 0
    for i in range(idx, min(idx + 100000, len(text))):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return text[idx : i + 1]
    return None


def _extract_image_urls_from_slides(slides: list[dict]) -> list[str]:
    """Extract the best image URL from each carousel slide."""
    urls: list[str] = []
    for slide in slides:
        candidates = slide.get("image_versions2", {}).get("candidates", [])
        if candidates:
            best = max(
                candidates, key=lambda c: c.get("width", 0) * c.get("height", 0)
            )
            url = best.get("url", "")
            if url:
                urls.append(url)
    return urls


def _extract_sidecar_urls(page: str) -> list[str]:
    """Extract display_url from edge_sidecar_to_children or carousel_media in page HTML."""
    urls: list[str] = []

    for m in re.finditer(r'"edge_sidecar_to_children"\s*:\s*\{', page):
        blob_str = _extract_json_object(page, m.start())
        if not blob_str:
            continue
        try:
            key_prefix = '"edge_sidecar_to_children":'
            json_str = blob_str[blob_str.index(key_prefix) + len(key_prefix) :]
            blob = json.loads(json_str)
            for edge in blob.get("edges", []):
                node = edge.get("node", {})
                display = node.get("display_url", "")
                if display:
                    urls.append(_unescape_url(display))
        except (json.JSONDecodeError, ValueError):
            continue

    if urls:
        return urls

    for m in re.finditer(r'"carousel_media"\s*:\s*\[', page):
        arr_str = _extract_json_array(page, m.start() + len('"carousel_media":'))
        if not arr_str:
            continue
        try:
            items = json.loads(arr_str)
            urls = _extract_image_urls_from_slides(items)
        except (json.JSONDecodeError, ValueError):
            continue

    return urls


def _extract_display_urls(page: str) -> list[str]:
    """Extract display_url values from page."""
    urls: list[str] = []
    seen: set[str] = set()

    for m in re.finditer(r'"shortcode_media"\s*:\s*\{', page):
        block_end = min(m.start() + 100000, len(page))
        block = page[m.start() : block_end]
        for dm in re.finditer(r'"display_url"\s*:\s*"(https?://[^"]+)"', block):
            raw = _unescape_url(dm.group(1))
            if raw not in seen:
                seen.add(raw)
                urls.append(raw)

    if not urls:
        for dm in re.finditer(r'"display_url"\s*:\s*"(https?://[^"]+)"', page):
            raw = _unescape_url(dm.group(1))
            if raw not in seen:
                seen.add(raw)
                urls.append(raw)

    return urls


async def download_single_image(url: str, info: dict) -> DownloadResult:
    """Download a single image post using yt-dlp metadata or HTTP fallback."""
    image_url = get_best_image_url(info)
    if image_url:
        return await fetch_single_image(image_url, info)
    logger.warning("[Instagram] No image URL in metadata, falling back to HTTP")
    return await download_post_via_http(url)


async def fetch_single_image(image_url: str, info: dict) -> DownloadResult:
    """Fetch a single image from a direct URL."""
    logger.info("[Instagram] Downloading single image")

    try:
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, headers=_MOBILE_HEADERS
        ) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            buffer = io.BytesIO(resp.content)
            file_size = len(resp.content)
            buffer.seek(0)
    except Exception as e:
        raise DownloadError(
            f"Image download failed: {e}",
            platform="instagram",
        )

    caption = info.get("title") or info.get("description")
    if caption == "NA":
        caption = None

    return DownloadResult(
        buffer=buffer,
        filename="instagram_image.jpg",
        file_size=file_size,
        media_type=MediaType.IMAGE,
        caption=caption,
    )


async def download_post_via_http(url: str) -> DownloadResult:
    """Download post images via HTTP when yt-dlp can't handle them."""
    shortcode = extract_shortcode(url)
    if not shortcode:
        raise DownloadError(
            "Could not extract post shortcode from URL",
            platform="instagram",
            retryable=False,
        )

    try:
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, headers=_MOBILE_HEADERS
        ) as client:
            image_urls = await _fetch_api_images(client, shortcode)

            if not image_urls:
                image_urls = await _extract_post_page_images(client, shortcode)

            if not image_urls:
                image_urls = await _extract_embed_page_images(client, shortcode)

            if image_urls:
                logger.info(
                    f"[Instagram] Downloading {len(image_urls)} image(s) for post {shortcode}"
                )
                return await _fetch_images_to_result(client, image_urls, url)

            return await _fetch_media_endpoint(client, shortcode, url)

    except DownloadError:
        raise
    except Exception as e:
        raise DownloadError(
            f"Image download failed: {e}",
            platform="instagram",
        )


async def _fetch_api_images(
    client: httpx.AsyncClient, shortcode: str
) -> list[str]:
    """Try Instagram's ?__a=1&__d=dis JSON API to get post media."""
    api_url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"
    logger.info("[Instagram] Trying API endpoint for post images")

    try:
        resp = await client.get(api_url)
        if resp.status_code != 200:
            return []

        data = resp.json()
        items = data.get("items", [])
        if not items:
            return []

        item = items[0]
        media_type = item.get("media_type")
        if media_type == 2:
            logger.info("[Instagram] API says this is a video, not an image post")
            return []

        carousel = item.get("carousel_media", [])
        if carousel or media_type == 8:
            slides = carousel or []
            image_slides = [s for s in slides if s.get("media_type", 1) != 2]
            urls = _extract_image_urls_from_slides(image_slides)
            logger.info(f"[Instagram] API found {len(urls)} carousel image(s)")
            return urls

        candidates = item.get("image_versions2", {}).get("candidates", [])
        if candidates:
            best = max(
                candidates,
                key=lambda c: c.get("width", 0) * c.get("height", 0),
            )
            url = best.get("url", "")
            if url:
                logger.info("[Instagram] API found 1 image")
                return [url]

        return []

    except Exception as e:
        logger.debug(f"[Instagram] API extraction failed: {e}")
        return []


async def _extract_post_page_images(
    client: httpx.AsyncClient, shortcode: str
) -> list[str]:
    """Fetch the post page HTML and extract images from embedded JSON."""
    post_url = f"https://www.instagram.com/p/{shortcode}/"
    logger.info("[Instagram] Trying post page for embedded JSON")

    try:
        resp = await client.get(post_url)
        if resp.status_code != 200:
            return []

        page = resp.text
        urls = _extract_sidecar_urls(page)
        if urls:
            logger.info(f"[Instagram] Post page sidecar found {len(urls)} image(s)")
        return urls

    except Exception as e:
        logger.debug(f"[Instagram] Post page extraction failed: {e}")
        return []


async def _extract_embed_page_images(
    client: httpx.AsyncClient, shortcode: str
) -> list[str]:
    """Fetch the embed page and extract post images from its JSON/HTML."""
    embed_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
    logger.info("[Instagram] Trying embed page for post images")

    try:
        resp = await client.get(embed_url)
        if resp.status_code != 200:
            return []

        page = resp.text

        sidecar = _extract_sidecar_urls(page)
        if sidecar:
            logger.info(f"[Instagram] Embed sidecar found {len(sidecar)} image(s)")
            return sidecar

        display_urls = _extract_display_urls(page)
        if display_urls:
            logger.info(
                f"[Instagram] Embed display_url found {len(display_urls)} image(s)"
            )
            return display_urls

        return []

    except Exception as e:
        logger.debug(f"[Instagram] Embed page extraction failed: {e}")
        return []


async def _fetch_images_to_result(
    client: httpx.AsyncClient,
    image_urls: list[str],
    original_url: str,
) -> DownloadResult:
    """Download images from URLs into BytesIO buffers and return a DownloadResult."""
    buffers: list[io.BytesIO] = []
    for i, img_url in enumerate(image_urls):
        try:
            resp = await client.get(img_url)
            resp.raise_for_status()
            buf = io.BytesIO(resp.content)
            buf.seek(0)
            buffers.append(buf)
            logger.debug(
                f"[Instagram] Image {i+1}/{len(image_urls)}: "
                f"{len(resp.content)} bytes"
            )
        except Exception as e:
            logger.warning(f"[Instagram] Failed image {i+1}: {e}")

    if not buffers:
        raise DownloadError(
            "Failed to download any images",
            platform="instagram",
        )

    caption = await _scrape_caption(client, original_url)
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
        filename="instagram_image_1.jpg",
        file_size=first_size,
        media_type=MediaType.IMAGES,
        caption=caption,
        extra_buffers=buffers[1:],
    )


async def _fetch_media_endpoint(
    client: httpx.AsyncClient,
    shortcode: str,
    original_url: str,
) -> DownloadResult:
    """Download single image via Instagram's /media/?size=l endpoint."""
    media_url = f"https://www.instagram.com/p/{shortcode}/media/?size=l"
    logger.info("[Instagram] Fetching image via /media/ endpoint (single image)")

    resp = await client.get(media_url)
    resp.raise_for_status()

    content_type = resp.headers.get("content-type", "")
    if "image" not in content_type:
        raise DownloadError(
            f"Expected image, got {content_type}",
            platform="instagram",
        )

    buffer = io.BytesIO(resp.content)
    file_size = len(resp.content)
    buffer.seek(0)

    logger.info(f"[Instagram] Downloaded image: {file_size / 1024:.1f} KB")

    caption = await _scrape_caption(client, original_url)

    return DownloadResult(
        buffer=buffer,
        filename="instagram_image.jpg",
        file_size=file_size,
        media_type=MediaType.IMAGE,
        caption=caption,
    )


async def _scrape_caption(client: httpx.AsyncClient, url: str) -> str | None:
    """Try to get the post caption from page meta tags."""
    try:
        resp = await client.get(url)
        if resp.status_code == 200:
            match = re.search(
                r'<meta property="og:title" content="([^"]+)"', resp.text
            )
            if match:
                title = htmlmod.unescape(match.group(1)).strip()
                if title:
                    return title
    except Exception:
        pass
    return None

