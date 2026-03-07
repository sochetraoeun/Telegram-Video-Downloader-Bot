"""TikTok media downloader — downloads videos and images directly into memory."""

import io
import asyncio
import json
import re
import html as htmlmod

import httpx
from loguru import logger

from src.downloaders.base_downloader import (
    BaseDownloader, DownloadResult, DownloadError, MediaType,
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


class TikTokDownloader(BaseDownloader):
    """Downloads TikTok videos and images using yt-dlp + HTTP fallback."""

    platform = "tiktok"

    async def supports(self, url: str) -> bool:
        pattern = re.compile(
            r"https?://(www\.|vm\.|vt\.)?tiktok\.com/.+", re.IGNORECASE
        )
        return bool(pattern.match(url))

    async def download(self, url: str) -> DownloadResult:
        """Download TikTok media (video or images) into memory."""
        logger.info(f"[TikTok] Downloading: {url}")

        # Try yt-dlp first for video content
        try:
            info = await self._extract_info(url)
            if self._is_image_post(info):
                return await self._download_images_from_info(url, info)
            return await self._download_video(url, info)
        except DownloadError as e:
            if "Unsupported URL" in e.message or "no video" in e.message.lower():
                logger.info("[TikTok] yt-dlp failed, trying HTTP scrape fallback for images")
                return await self._download_images_via_scrape(url)
            raise

    async def _extract_info(self, url: str) -> dict:
        """Extract metadata with yt-dlp --dump-json."""
        try:
            process = await asyncio.create_subprocess_exec(
                "yt-dlp",
                "--no-warnings",
                "--no-check-certificates",
                "--dump-json",
                "--quiet",
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=30
            )

            if process.returncode != 0:
                error_msg = stderr.decode().strip() if stderr else "Unknown error"
                raise DownloadError(
                    f"yt-dlp info extraction failed: {error_msg}",
                    platform=self.platform,
                )

            raw = stdout.decode().strip()
            if not raw:
                raise DownloadError(
                    "yt-dlp returned no data",
                    platform=self.platform,
                )

            return json.loads(raw)

        except json.JSONDecodeError:
            raise DownloadError(
                "Failed to parse media info",
                platform=self.platform,
            )
        except asyncio.TimeoutError:
            raise DownloadError(
                "Info extraction timed out (>30s)",
                platform=self.platform,
            )
        except DownloadError:
            raise
        except Exception as e:
            raise DownloadError(
                f"Info extraction failed: {e}",
                platform=self.platform,
            )

    def _is_image_post(self, info: dict) -> bool:
        """Detect if the post is an image slideshow."""
        if info.get("entries"):
            return any(
                e.get("ext") in ("jpg", "jpeg", "png", "webp")
                for e in info["entries"]
            )

        ext = info.get("ext", "")
        if ext in ("jpg", "jpeg", "png", "webp"):
            return True

        for fmt in info.get("formats", []):
            if fmt.get("format_note") == "Image":
                return True

        return False

    async def _download_video(self, url: str, info: dict) -> DownloadResult:
        """Download video bytes into memory."""
        try:
            process = await asyncio.create_subprocess_exec(
                "yt-dlp",
                "--no-warnings",
                "--no-check-certificates",
                "--format", "best[filesize<50M]/best",
                "--output", "-",
                "--quiet",
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=120
            )

            if process.returncode != 0:
                error_msg = stderr.decode().strip() if stderr else "Unknown error"
                raise DownloadError(
                    f"yt-dlp failed: {error_msg}",
                    platform=self.platform,
                )

            if not stdout:
                raise DownloadError(
                    "No video data received",
                    platform=self.platform,
                )

            buffer = io.BytesIO(stdout)
            file_size = len(stdout)
            buffer.seek(0)

            logger.info(f"[TikTok] Downloaded video: {file_size / 1024 / 1024:.1f} MB")

            caption = info.get("title") or info.get("description")
            if caption == "NA":
                caption = None

            return DownloadResult(
                buffer=buffer,
                filename="tiktok_video.mp4",
                file_size=file_size,
                media_type=MediaType.VIDEO,
                caption=caption,
            )

        except asyncio.TimeoutError:
            raise DownloadError("Download timed out (>120s)", platform=self.platform)
        except DownloadError:
            raise
        except Exception as e:
            raise DownloadError(f"Unexpected error: {e}", platform=self.platform)

    async def _download_images_from_info(self, url: str, info: dict) -> DownloadResult:
        """Download images when yt-dlp metadata contains image URLs."""
        image_urls = self._collect_image_urls(info)
        if not image_urls:
            logger.warning("[TikTok] yt-dlp metadata had no image URLs, falling back to scrape")
            return await self._download_images_via_scrape(url)
        return await self._fetch_images(image_urls, info)

    async def _download_images_via_scrape(self, url: str) -> DownloadResult:
        """Fallback: scrape TikTok page HTML for photomode image URLs.

        yt-dlp doesn't support TikTok /photo/ URLs, so we fetch the page
        with a mobile user-agent and extract image URLs from the HTML.
        """
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
                platform=self.platform,
            )

        page = resp.text
        image_urls = self._extract_photomode_urls(page)

        if not image_urls:
            raise DownloadError(
                "No images found on this TikTok page",
                platform=self.platform,
                retryable=False,
            )

        caption = self._extract_title_from_html(page)
        return await self._fetch_images(image_urls, {"title": caption})

    def _extract_photomode_urls(self, html: str) -> list[str]:
        """Extract unique photomode image URLs from TikTok page HTML.

        TikTok embeds slideshow images as both raw URLs (in <link> tags)
        and unicode-escaped URLs (in inline JS data). We parse both forms
        and deduplicate by image content hash.
        """
        # Decode unicode escapes (\u002F -> /) in the page text
        decoded = html.replace(r"\u002F", "/").replace(r"\u0026", "&")

        # Match full-resolution photomode image URLs (exclude share-card thumbnails)
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

    def _extract_title_from_html(self, html: str) -> str | None:
        """Extract post title/caption from page HTML."""
        match = re.search(r"<title>([^<]+)</title>", html)
        if match:
            title = htmlmod.unescape(match.group(1)).strip()
            if title and title != "TikTok" and "Make Your Day" not in title:
                return title
        return None

    async def _fetch_images(
        self, image_urls: list[str], info: dict
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
                        f"[TikTok] Image {i+1}/{len(image_urls)}: {len(resp.content)} bytes"
                    )
                except Exception as e:
                    logger.warning(f"[TikTok] Failed to download image {i+1}: {e}")

        if not buffers:
            raise DownloadError(
                "Failed to download any images",
                platform=self.platform,
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

    def _collect_image_urls(self, info: dict) -> list[str]:
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
                    "jpg", "jpeg", "png", "webp"
                ):
                    url = fmt.get("url")
                    if url:
                        urls.append(url)

        return urls
