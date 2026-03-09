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
            return await self._download_image_via_http(url)

        if self._is_carousel(info):
            return await self._download_carousel(url, info)

        if self._is_image_post(info):
            return await self._download_single_image(url, info)

        return await self._download_video(url, info)

    async def _extract_info(self, url: str) -> dict | None:
        """Extract metadata with yt-dlp --dump-json.

        Returns None if yt-dlp succeeds but produces no output
        (e.g. pure image posts that yt-dlp sees as 0-item playlists).
        """
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
                # Non-fatal: yt-dlp may just not support this content type
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
        return await self._download_image_via_http(url)

    async def _download_image_via_http(self, url: str) -> DownloadResult:
        """Fallback: scrape images from the Instagram embed page.

        yt-dlp can't extract pure image posts (reports 0 items).
        We fetch the /embed/captioned/ page which contains authenticated
        image URLs in <img src> and <srcset> attributes for all carousel items.
        Falls back to /media/?size=l for single images.
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
                timeout=20, follow_redirects=True, headers=_MOBILE_HEADERS
            ) as client:
                image_urls = await self._scrape_embed_images(client, shortcode)

                if not image_urls:
                    image_urls = await self._scrape_graphql_images(client, shortcode)

                if image_urls:
                    return await self._fetch_scraped_images(
                        client, image_urls, url
                    )

                return await self._fetch_media_endpoint(client, shortcode, url)

        except DownloadError:
            raise
        except Exception as e:
            raise DownloadError(
                f"Image download failed: {e}",
                platform=self.platform,
            )

    async def _scrape_embed_images(
        self, client: httpx.AsyncClient, shortcode: str
    ) -> list[str]:
        """Scrape image URLs from the Instagram embed page.

        The embed page renders authenticated CDN URLs in <img src> and
        <srcset> attributes. We extract them, filter out profile pics /
        tiny thumbnails, and keep the highest resolution variant per
        unique image.
        """
        embed_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
        logger.info("[Instagram] Fetching embed page for image URLs")

        resp = await client.get(embed_url)
        if resp.status_code != 200:
            return []

        page = resp.text
        all_urls: list[str] = []

        cdn_pattern = re.compile(
            r"(https?://[a-z0-9\-]+\.cdninstagram\.com/[^\s\"']+)"
            r"|(https?://instagram\.[a-z.]+\.fbcdn\.net/[^\s\"']+)"
        )

        for m in cdn_pattern.finditer(page):
            raw = m.group(0)
            url_clean = htmlmod.unescape(raw).split("\\")[0].rstrip('"\')')
            all_urls.append(url_clean)

        for u in re.findall(
            r'src="(https://instagram[^"]+\.fbcdn\.net[^"]+)"', page
        ):
            all_urls.append(htmlmod.unescape(u))

        for srcset in re.findall(r'srcset="([^"]+)"', page):
            for u in re.findall(
                r"(https://[^\s,]+)", srcset
            ):
                decoded = htmlmod.unescape(u)
                if "cdninstagram" in decoded or "fbcdn" in decoded:
                    all_urls.append(decoded)

        skip_patterns = ("e0_s150x150", "s150x150", "t51.2885", "/s64x64/", "/s96x96/")
        image_exts = (".jpg", ".jpeg", ".png", ".webp")

        filtered: list[str] = []
        for u in all_urls:
            if any(p in u for p in skip_patterns):
                continue
            path = u.split("?")[0]
            if any(path.endswith(ext) for ext in image_exts):
                filtered.append(u)

        by_id: dict[str, tuple[str, int]] = {}
        for u in filtered:
            m_id = re.search(r"/(\d+_\d+_\d+_\w+)\.\w+", u)
            if m_id:
                iid = m_id.group(1)
            else:
                iid = u.split("?")[0].rsplit("/", 1)[-1]

            size = re.search(r"[/_](\d{3,4})x", u)
            res = int(size.group(1)) if size else 0
            if iid not in by_id or res > by_id[iid][1]:
                by_id[iid] = (u, res)

        urls = [url for url, _ in by_id.values()]
        logger.info(f"[Instagram] Found {len(urls)} image(s) in embed page")
        return urls

    async def _scrape_graphql_images(
        self, client: httpx.AsyncClient, shortcode: str
    ) -> list[str]:
        """Fallback: extract carousel image URLs from the post page's embedded JSON."""
        post_url = f"https://www.instagram.com/p/{shortcode}/"
        logger.info("[Instagram] Trying page JSON extraction for carousel images")

        try:
            resp = await client.get(post_url)
            if resp.status_code != 200:
                return []

            page = resp.text
            urls: list[str] = []

            for pattern in [
                r'"display_url"\s*:\s*"(https?://[^"]+)"',
                r'"image_versions2".*?"url"\s*:\s*"(https?://[^"]+)"',
                r'"display_resources".*?"src"\s*:\s*"(https?://[^"]+)"',
            ]:
                for match in re.finditer(pattern, page):
                    raw = match.group(1).replace("\\u0026", "&")
                    if raw not in urls:
                        urls.append(raw)

            if not urls:
                for m in re.finditer(
                    r'"(https?://(?:[a-z0-9-]+\.)?cdninstagram\.com/[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
                    page,
                ):
                    raw = m.group(1).replace("\\u0026", "&")
                    if any(s in raw for s in ("s150x150", "s64x64", "s96x96", "t51.2885")):
                        continue
                    if raw not in urls:
                        urls.append(raw)

            logger.info(f"[Instagram] Page JSON extraction found {len(urls)} image(s)")
            return urls

        except Exception as e:
            logger.warning(f"[Instagram] Page JSON extraction failed: {e}")
            return []

    async def _fetch_scraped_images(
        self,
        client: httpx.AsyncClient,
        image_urls: list[str],
        original_url: str,
    ) -> DownloadResult:
        """Download images from scraped URLs into BytesIO buffers."""
        logger.info(f"[Instagram] Downloading {len(image_urls)} image(s)")

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
        logger.info("[Instagram] Fetching image via /media/ endpoint")

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

    def _extract_shortcode(self, url: str) -> str | None:
        """Extract the post shortcode from an Instagram URL."""
        match = re.search(r"instagram\.com/(?:p|reel|reels)/([A-Za-z0-9_-]+)", url)
        return match.group(1) if match else None

    # ── Carousel download ─────────────────────────────────────────────

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
