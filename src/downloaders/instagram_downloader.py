"""Instagram media downloader — downloads videos and images directly into memory."""

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


class InstagramDownloader(BaseDownloader):
    """Downloads Instagram videos and images using yt-dlp + HTTP fallback."""

    platform = "instagram"

    _STORY_PATTERN = re.compile(
        r"https?://(www\.)?instagram\.com/stories/.+", re.IGNORECASE
    )

    async def supports(self, url: str) -> bool:
        pattern = re.compile(
            r"https?://(www\.)?instagram\.com/(reel|p|stories|reels)/.+", re.IGNORECASE
        )
        return bool(pattern.match(url))

    async def download(self, url: str) -> DownloadResult:
        """Download Instagram media (video or images) into memory."""
        logger.info(f"[Instagram] Downloading: {url}")

        if self._STORY_PATTERN.match(url):
            raise DownloadError(
                "Instagram Stories require login and are not supported. "
                "Try sending a Reel or Post link instead.",
                platform=self.platform,
                retryable=False,
            )

        info = await self._extract_info(url)

        if info is None:
            logger.info("[Instagram] yt-dlp returned no data, trying HTTP fallback")
            return await self._download_post_via_http(url)

        if self._is_carousel(info):
            return await self._download_carousel(url, info)

        if self._is_image_post(info):
            return await self._download_single_image(url, info)

        return await self._download_video(url, info)

    # ── yt-dlp info extraction ─────────────────────────────────────────

    async def _extract_info(self, url: str) -> dict | None:
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
                logger.warning(f"[Instagram] yt-dlp returned error: {error_msg}")
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
            logger.warning("[Instagram] yt-dlp output was not valid JSON")
            return None
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

    def _is_carousel(self, info: dict) -> bool:
        if info.get("_type") == "playlist" and info.get("entries"):
            return len(info["entries"]) > 1
        return False

    def _is_image_post(self, info: dict) -> bool:
        video_formats = [
            f for f in info.get("formats", [])
            if f.get("vcodec", "none") != "none"
        ]
        if video_formats:
            return False

        ext = info.get("ext", "")
        if ext in ("jpg", "jpeg", "png", "webp"):
            return True

        if not video_formats and info.get("url"):
            return True

        return False

    # ── Video download ────────────────────────────────────────────────

    async def _download_video(self, url: str, info: dict) -> DownloadResult:
        """Download video bytes into memory via yt-dlp."""
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

            logger.info(f"[Instagram] Downloaded video: {file_size / 1024 / 1024:.1f} MB")

            caption = info.get("title") or info.get("description")
            if caption == "NA":
                caption = None

            return DownloadResult(
                buffer=buffer,
                filename="instagram_video.mp4",
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

    # ── Single image download ─────────────────────────────────────────

    async def _download_single_image(self, url: str, info: dict) -> DownloadResult:
        """Download a single image post using yt-dlp metadata or HTTP fallback."""
        image_url = self._get_best_image_url(info)
        if image_url:
            return await self._fetch_single_image(image_url, info)
        logger.warning("[Instagram] No image URL in metadata, falling back to HTTP")
        return await self._download_post_via_http(url)

    # ── HTTP fallback for image posts (single + carousel) ─────────────

    async def _download_post_via_http(self, url: str) -> DownloadResult:
        """Download post images via HTTP when yt-dlp can't handle them.

        Uses structured APIs first (JSON with explicit post media),
        then falls back to embed page scraping. Only downloads media
        that belongs to the specific post — never profile data.
        """
        shortcode = self._extract_shortcode(url)
        if not shortcode:
            raise DownloadError(
                "Could not extract post shortcode from URL",
                platform=self.platform,
                retryable=False,
            )

        try:
            async with httpx.AsyncClient(
                timeout=30, follow_redirects=True, headers=_MOBILE_HEADERS
            ) as client:
                # 1) Structured JSON API — most reliable, returns only post media
                image_urls = await self._fetch_api_images(client, shortcode)

                # 2) Post page — extract sidecar/carousel JSON from HTML
                if not image_urls:
                    image_urls = await self._extract_post_page_images(client, shortcode)

                # 3) Embed page — structured carousel data from embed JS
                if not image_urls:
                    image_urls = await self._extract_embed_page_images(client, shortcode)

                if image_urls:
                    logger.info(f"[Instagram] Downloading {len(image_urls)} image(s) for post {shortcode}")
                    return await self._fetch_images_to_result(client, image_urls, url)

                # 4) Last resort — /media/?size=l (always returns 1 image)
                return await self._fetch_media_endpoint(client, shortcode, url)

        except DownloadError:
            raise
        except Exception as e:
            raise DownloadError(
                f"Image download failed: {e}",
                platform=self.platform,
            )

    async def _fetch_api_images(
        self, client: httpx.AsyncClient, shortcode: str
    ) -> list[str]:
        """Try Instagram's ?__a=1&__d=dis JSON API to get post media.

        Returns image URLs only for media in this specific post.
        For carousels, returns all slide images.
        For single posts, returns the one image.
        """
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

            carousel = item.get("carousel_media", [])
            if carousel:
                urls = self._extract_image_urls_from_slides(carousel)
                logger.info(f"[Instagram] API found {len(urls)} carousel image(s)")
                return urls

            candidates = item.get("image_versions2", {}).get("candidates", [])
            if candidates:
                best = max(candidates, key=lambda c: c.get("width", 0) * c.get("height", 0))
                url = best.get("url", "")
                if url:
                    logger.info("[Instagram] API found 1 image")
                    return [url]

            return []

        except Exception as e:
            logger.debug(f"[Instagram] API extraction failed: {e}")
            return []

    async def _extract_post_page_images(
        self, client: httpx.AsyncClient, shortcode: str
    ) -> list[str]:
        """Fetch the post page HTML and extract images from embedded JSON.

        Looks for edge_sidecar_to_children (GraphQL) or carousel_media
        (API-style) JSON structures embedded in the page.
        """
        post_url = f"https://www.instagram.com/p/{shortcode}/"
        logger.info("[Instagram] Trying post page for embedded JSON")

        try:
            resp = await client.get(post_url)
            if resp.status_code != 200:
                return []

            page = resp.text
            urls = self._extract_sidecar_urls(page)
            if urls:
                logger.info(f"[Instagram] Post page sidecar found {len(urls)} image(s)")
            return urls

        except Exception as e:
            logger.debug(f"[Instagram] Post page extraction failed: {e}")
            return []

    async def _extract_embed_page_images(
        self, client: httpx.AsyncClient, shortcode: str
    ) -> list[str]:
        """Fetch the embed page and extract post images from its JSON/HTML.

        The embed page contains carousel data as JSON in <script> tags.
        We extract only from structured data, not from loose CDN URLs,
        to avoid grabbing profile pictures or unrelated images.
        """
        embed_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
        logger.info("[Instagram] Trying embed page for post images")

        try:
            resp = await client.get(embed_url)
            if resp.status_code != 200:
                return []

            page = resp.text

            sidecar = self._extract_sidecar_urls(page)
            if sidecar:
                logger.info(f"[Instagram] Embed sidecar found {len(sidecar)} image(s)")
                return sidecar

            display_urls = self._extract_display_urls(page)
            if display_urls:
                logger.info(f"[Instagram] Embed display_url found {len(display_urls)} image(s)")
                return display_urls

            return []

        except Exception as e:
            logger.debug(f"[Instagram] Embed page extraction failed: {e}")
            return []

    # ── Structured JSON extraction helpers ─────────────────────────────

    def _extract_image_urls_from_slides(self, slides: list[dict]) -> list[str]:
        """Extract the best image URL from each carousel slide."""
        urls: list[str] = []
        for slide in slides:
            candidates = slide.get("image_versions2", {}).get("candidates", [])
            if candidates:
                best = max(candidates, key=lambda c: c.get("width", 0) * c.get("height", 0))
                url = best.get("url", "")
                if url:
                    urls.append(url)
        return urls

    def _extract_sidecar_urls(self, page: str) -> list[str]:
        """Extract display_url from edge_sidecar_to_children or carousel_media in page HTML."""
        urls: list[str] = []

        # GraphQL format: edge_sidecar_to_children
        for m in re.finditer(r'"edge_sidecar_to_children"\s*:\s*\{', page):
            blob_str = self._extract_json_object(page, m.start())
            if not blob_str:
                continue
            try:
                key_prefix = '"edge_sidecar_to_children":'
                json_str = blob_str[blob_str.index(key_prefix) + len(key_prefix):]
                blob = json.loads(json_str)
                for edge in blob.get("edges", []):
                    node = edge.get("node", {})
                    display = node.get("display_url", "")
                    if display:
                        urls.append(self._unescape_url(display))
            except (json.JSONDecodeError, ValueError):
                continue

        if urls:
            return urls

        # API format: carousel_media
        for m in re.finditer(r'"carousel_media"\s*:\s*\[', page):
            arr_str = self._extract_json_array(page, m.start() + len('"carousel_media":'))
            if not arr_str:
                continue
            try:
                items = json.loads(arr_str)
                urls = self._extract_image_urls_from_slides(items)
            except (json.JSONDecodeError, ValueError):
                continue

        return urls

    def _extract_display_urls(self, page: str) -> list[str]:
        """Extract display_url values from page — only those inside shortcode_media or similar post blocks."""
        urls: list[str] = []
        seen: set[str] = set()

        for m in re.finditer(r'"shortcode_media"\s*:\s*\{', page):
            block_end = min(m.start() + 100000, len(page))
            block = page[m.start():block_end]
            for dm in re.finditer(r'"display_url"\s*:\s*"(https?://[^"]+)"', block):
                raw = self._unescape_url(dm.group(1))
                if raw not in seen:
                    seen.add(raw)
                    urls.append(raw)

        if not urls:
            for dm in re.finditer(r'"display_url"\s*:\s*"(https?://[^"]+)"', page):
                raw = self._unescape_url(dm.group(1))
                if raw not in seen:
                    seen.add(raw)
                    urls.append(raw)

        return urls

    # ── Image fetching ─────────────────────────────────────────────────

    async def _fetch_images_to_result(
        self,
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
                platform=self.platform,
            )

        caption = await self._scrape_caption(client, original_url)
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
        self,
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
                platform=self.platform,
            )

        buffer = io.BytesIO(resp.content)
        file_size = len(resp.content)
        buffer.seek(0)

        logger.info(f"[Instagram] Downloaded image: {file_size / 1024:.1f} KB")

        caption = await self._scrape_caption(client, original_url)

        return DownloadResult(
            buffer=buffer,
            filename="instagram_image.jpg",
            file_size=file_size,
            media_type=MediaType.IMAGE,
            caption=caption,
        )

    async def _scrape_caption(self, client: httpx.AsyncClient, url: str) -> str | None:
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

    # ── Carousel download (yt-dlp path) ───────────────────────────────

    async def _download_carousel(self, url: str, info: dict) -> DownloadResult:
        """Download a carousel post (multiple images/videos) into memory."""
        entries = info.get("entries", [])
        if not entries:
            raise DownloadError("Carousel has no entries", platform=self.platform)

        logger.info(f"[Instagram] Downloading carousel with {len(entries)} items")

        buffers: list[io.BytesIO] = []
        media_types: list[MediaType] = []

        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True, headers=_MOBILE_HEADERS
        ) as client:
            for i, entry in enumerate(entries):
                ext = entry.get("ext", "")
                is_image = ext in ("jpg", "jpeg", "png", "webp")

                if is_image:
                    img_url = self._get_best_image_url(entry)
                    if img_url:
                        try:
                            resp = await client.get(img_url)
                            resp.raise_for_status()
                            buf = io.BytesIO(resp.content)
                            buf.seek(0)
                            buffers.append(buf)
                            media_types.append(MediaType.IMAGE)
                            logger.debug(
                                f"[Instagram] Carousel item {i+1}: "
                                f"image ({len(resp.content)} bytes)"
                            )
                            continue
                        except Exception as e:
                            logger.warning(
                                f"[Instagram] Failed carousel image {i+1}: {e}"
                            )

                entry_url = entry.get("webpage_url") or entry.get("url") or url
                try:
                    video_buf = await self._download_video_bytes(entry_url)
                    buffers.append(video_buf)
                    media_types.append(MediaType.VIDEO)
                    logger.debug(f"[Instagram] Carousel item {i+1}: video")
                except Exception as e:
                    logger.warning(f"[Instagram] Failed carousel video {i+1}: {e}")

        if not buffers:
            raise DownloadError(
                "Failed to download any carousel items",
                platform=self.platform,
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
                filename="instagram_image.jpg" if all_images else "instagram_video.mp4",
                file_size=first_size,
                media_type=media_types[0],
                caption=caption,
            )

        return DownloadResult(
            buffer=first,
            filename="instagram_carousel_1.jpg" if all_images else "instagram_carousel_1",
            file_size=first_size,
            media_type=MediaType.IMAGES,
            caption=caption,
            extra_buffers=buffers[1:],
        )

    async def _download_video_bytes(self, url: str) -> io.BytesIO:
        """Download a single video entry into a BytesIO buffer."""
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

        if process.returncode != 0 or not stdout:
            raise DownloadError(
                "Video download failed for carousel item",
                platform=self.platform,
            )

        buf = io.BytesIO(stdout)
        buf.seek(0)
        return buf

    # ── Helpers ────────────────────────────────────────────────────────

    def _extract_shortcode(self, url: str) -> str | None:
        """Extract the post shortcode from an Instagram URL."""
        match = re.search(r"instagram\.com/(?:p|reel|reels)/([A-Za-z0-9_-]+)", url)
        return match.group(1) if match else None

    async def _fetch_single_image(
        self, image_url: str, info: dict
    ) -> DownloadResult:
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
                platform=self.platform,
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

    def _get_best_image_url(self, info: dict) -> str | None:
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

    @staticmethod
    def _unescape_url(raw: str) -> str:
        return raw.replace("\\u0026", "&").replace("\\/", "/")

    @staticmethod
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
                    return text[idx:i + 1]
        return None

    @staticmethod
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
                    return text[idx:i + 1]
        return None
