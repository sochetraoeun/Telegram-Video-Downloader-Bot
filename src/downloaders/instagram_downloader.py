"""Instagram media downloader — downloads videos and images directly into memory."""

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
    BaseDownloader,
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


class InstagramDownloader(BaseDownloader):
    """Downloads Instagram videos and images using yt-dlp + HTTP fallback."""

    platform = "instagram"

    _STORY_PATTERN = re.compile(
        r"https?://(www\.)?instagram\.com/stories/.+", re.IGNORECASE
    )

    def _get_cookies_args(self, url: str) -> list[str]:
        """Return --cookies args for story URLs when cookies file is configured."""
        if not self._STORY_PATTERN.match(url):
            return []
        path = settings.instagram_cookies_file
        if not path:
            return []
        abs_path = os.path.abspath(path)
        if not os.path.exists(abs_path):
            logger.warning(f"[Instagram] Cookies file not found: {abs_path}")
            return []
        return ["--cookies", abs_path]

    def _normalize_story_url(self, url: str) -> str:
        """Strip query params from story URLs — some can cause yt-dlp to fail."""
        if not self._STORY_PATTERN.match(url):
            return url
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))

    async def supports(self, url: str) -> bool:
        pattern = re.compile(
            r"https?://(www\.)?instagram\.com/(reel|p|stories|reels)/.+",
            re.IGNORECASE,
        )
        return bool(pattern.match(url))

    async def download(self, url: str) -> DownloadResult:
        """Download Instagram media (video or images) into memory."""
        url = self._normalize_story_url(url)
        logger.info(f"[Instagram] Downloading: {url}")

        if self._STORY_PATTERN.match(url):
            if not self._get_cookies_args(url):
                raise DownloadError(
                    "Instagram Stories require login and are not supported. "
                    "Try sending a Reel or Post link instead.",
                    platform=self.platform,
                    retryable=False,
                )

        is_reel = bool(re.search(r"instagram\.com/reels?/", url, re.IGNORECASE))

        info = await self._extract_info(url)

        if info is not None:
            logger.info(
                f"[Instagram] yt-dlp returned info: ext={info.get('ext')}, "
                f"vcodec={info.get('vcodec', 'N/A')}, "
                f"formats={len(info.get('formats', []))}, "
                f"type={info.get('_type', 'single')}"
            )

            if self._is_carousel(info):
                return await self._download_carousel(url, info)

            if self._is_image_post(info):
                return await download_single_image(url, info)

            return await download_video(url, info, self._get_cookies_args)

        if self._STORY_PATTERN.match(url):
            raise DownloadError(
                "Could not fetch story — session may have expired. Please update the cookies file.",
                platform=self.platform,
                retryable=False,
            )
        if is_reel:
            logger.warning("[Instagram] yt-dlp failed for reel, retrying download")
            raise DownloadError(
                "Could not extract reel video data",
                platform=self.platform,
                retryable=True,
            )

        logger.info(
            "[Instagram] yt-dlp returned no data, trying HTTP fallback for images"
        )
        return await download_post_via_http(url)

    async def _extract_info(self, url: str) -> dict | None:
        """Extract metadata with yt-dlp --dump-json."""
        try:
            args = [
                "yt-dlp",
                "--no-warnings",
                "--no-check-certificates",
                "--dump-json",
                "--quiet",
            ]
            args.extend(self._get_cookies_args(url))
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
                logger.warning(f"[Instagram] yt-dlp returned error: {error_msg}")
                if self._STORY_PATTERN.match(url):
                    if "unreachable" in error_msg.lower():
                        raise DownloadError(
                            "Story could not be reached — it may have expired (stories last 24h) or the account may be private.",
                            platform=self.platform,
                            retryable=False,
                        )
                    if "login" in error_msg.lower() or "cookie" in error_msg.lower():
                        raise DownloadError(
                            "Instagram session expired. Please export fresh cookies and update the cookies file.",
                            platform=self.platform,
                            retryable=False,
                        )
                    raise DownloadError(
                        f"Story download failed: {error_msg[:200]}",
                        platform=self.platform,
                        retryable=False,
                    )
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
        ext = info.get("ext", "")
        vcodec = info.get("vcodec", "none")
        formats = info.get("formats", [])

        if ext in ("mp4", "webm", "mkv", "mov", "flv"):
            logger.debug(f"[Instagram] Not image: video ext={ext}")
            return False

        if vcodec not in ("none", None, ""):
            logger.debug(f"[Instagram] Not image: vcodec={vcodec}")
            return False

        video_formats = [
            f
            for f in formats
            if f.get("vcodec", "none") not in ("none", None, "")
        ]
        if video_formats:
            logger.debug(
                f"[Instagram] Not image: {len(video_formats)} video format(s) found"
            )
            return False

        audio_only_formats = [
            f
            for f in formats
            if f.get("acodec", "none") not in ("none", None, "")
        ]
        if (
            audio_only_formats
            and not video_formats
            and ext not in ("jpg", "jpeg", "png", "webp")
        ):
            logger.debug(
                "[Instagram] Not image: has audio formats, likely a video"
            )
            return False

        if ext in ("jpg", "jpeg", "png", "webp"):
            logger.debug(f"[Instagram] Detected image: ext={ext}")
            return True

        logger.debug(f"[Instagram] Not image: ext={ext}, treating as video")
        return False

    async def _download_carousel(self, url: str, info: dict) -> DownloadResult:
        """Download a carousel post (multiple images/videos) into memory."""
        entries = info.get("entries", [])
        if not entries:
            raise DownloadError(
                "Carousel has no entries", platform=self.platform
            )

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
                    video_buf = await download_video_bytes(
                        entry_url, self._get_cookies_args
                    )
                    buffers.append(video_buf)
                    media_types.append(MediaType.VIDEO)
                    logger.debug(f"[Instagram] Carousel item {i+1}: video")
                except Exception as e:
                    logger.warning(
                        f"[Instagram] Failed carousel video {i+1}: {e}"
                    )

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
