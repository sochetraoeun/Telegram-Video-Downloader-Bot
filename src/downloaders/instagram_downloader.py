"""Instagram media downloader — routes Story, Post image, or Post video."""

import io
import asyncio
import json
import re

import httpx
from loguru import logger

from src.downloaders.base_downloader import (
    BaseDownloader,
    DownloadResult,
    DownloadError,
    MediaType,
)
from src.downloaders.instagram_story_download import download_story
from src.downloaders.instagram_image_download import get_best_image_url
from src.downloaders.instagram_post_image_download import (
    download_post_image,
    download_post_image_via_http,
    download_image_carousel,
)
from src.downloaders.instagram_post_video_download import (
    download_post_video,
    download_video_carousel,
    _cookies_fn,
)
from src.downloaders.instagram_video_download import download_video_bytes

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
    """Downloads Instagram media. Stories use cookies; Reels/Posts use image or video downloader."""

    platform = "instagram"

    _STORY_PATTERN = re.compile(
        r"https?://(www\.)?instagram\.com/stories/.+", re.IGNORECASE
    )

    async def supports(self, url: str) -> bool:
        pattern = re.compile(
            r"https?://(www\.)?instagram\.com/(reel|p|stories|reels)/.+",
            re.IGNORECASE,
        )
        return bool(pattern.match(url))

    async def download(self, url: str) -> DownloadResult:
        """Route to Story, Post image, or Post video downloader."""
        if self._STORY_PATTERN.match(url):
            logger.info("[Instagram] Routing to Story downloader (with cookies)")
            return await download_story(url)

        logger.info("[Instagram] Routing to Post (image or video)")
        return await self._download_post(url)

    @staticmethod
    def _is_carousel(info: dict) -> bool:
        if info.get("_type") == "playlist" and info.get("entries"):
            return len(info["entries"]) > 1
        return False

    @staticmethod
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

    @staticmethod
    def _is_all_images_carousel(info: dict) -> bool:
        entries = info.get("entries", [])
        return all(
            entry.get("ext", "") in ("jpg", "jpeg", "png", "webp")
            for entry in entries
        ) and bool(entries)

    @staticmethod
    def _is_all_videos_carousel(info: dict) -> bool:
        entries = info.get("entries", [])
        return all(
            entry.get("ext", "") not in ("jpg", "jpeg", "png", "webp")
            for entry in entries
        ) and bool(entries)

    @staticmethod
    async def _extract_info(url: str) -> dict | None:
        try:
            args = [
                "yt-dlp", "--no-warnings", "--no-check-certificates",
                "--dump-json", "--quiet",
            ]
            args.extend(_cookies_fn(url))
            args.append(url)
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            if process.returncode != 0:
                error_msg = stderr.decode().strip() if stderr else "Unknown error"
                logger.warning(f"[Instagram Post] yt-dlp error: {error_msg}")
                err_lower = error_msg.lower()
                if "login required" in err_lower or "rate-limit" in err_lower:
                    if not _cookies_fn(url):
                        raise DownloadError(
                            "Instagram Reels require login. Add INSTAGRAM_COOKIES_BASE64. See deploy.md.",
                            platform="instagram", retryable=False,
                        )
                    raise DownloadError(
                        "Instagram blocked (rate-limit or expired session). Update cookies.",
                        platform="instagram", retryable=False,
                    )
                return None
            raw = stdout.decode().strip()
            if not raw:
                return None
            lines = raw.split("\n")
            if len(lines) > 1:
                entries = [json.loads(line) for line in lines if line.strip()]
                return {"_type": "playlist", "entries": entries, "title": entries[0].get("title") if entries else None}
            return json.loads(lines[0])
        except json.JSONDecodeError:
            logger.warning("[Instagram Post] yt-dlp output was not valid JSON")
            return None
        except asyncio.TimeoutError:
            raise DownloadError("Info extraction timed out (>30s)", platform="instagram")
        except DownloadError:
            raise
        except Exception as e:
            raise DownloadError(f"Info extraction failed: {e}", platform="instagram")

    @staticmethod
    async def _download_mixed_carousel(url: str, info: dict) -> DownloadResult:
        entries = info.get("entries", [])
        if not entries:
            raise DownloadError("Carousel has no entries", platform="instagram")
        logger.info(f"[Instagram Post] Downloading mixed carousel with {len(entries)} items")
        buffers: list[io.BytesIO] = []
        media_types: list[MediaType] = []
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_MOBILE_HEADERS) as client:
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
                            logger.warning(f"[Instagram Post] Failed carousel image {i+1}: {e}")
                entry_url = entry.get("webpage_url") or entry.get("url") or url
                try:
                    video_buf = await download_video_bytes(entry_url, _cookies_fn)
                    buffers.append(video_buf)
                    media_types.append(MediaType.VIDEO)
                except Exception as e:
                    logger.warning(f"[Instagram Post] Failed carousel video {i+1}: {e}")
        if not buffers:
            raise DownloadError("Failed to download any carousel items", platform="instagram")
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
                filename="instagram_image.jpg" if all_images else "instagram_video.mp4",
                file_size=first_size, media_type=media_types[0], caption=caption,
            )
        return DownloadResult(
            buffer=first,
            filename="instagram_carousel_1.jpg" if all_images else "instagram_carousel_1",
            file_size=first_size, media_type=MediaType.IMAGES, caption=caption,
            extra_buffers=buffers[1:],
        )

    @classmethod
    async def _download_post(cls, url: str) -> DownloadResult:
        """Route to image or video downloader based on content type."""
        logger.info(f"[Instagram Post] Downloading: {url}")
        info = await cls._extract_info(url)
        if info is not None:
            logger.info(f"[Instagram Post] yt-dlp returned info: ext={info.get('ext')}, type={info.get('_type', 'single')}")
            if cls._is_carousel(info):
                if cls._is_all_images_carousel(info):
                    return await download_image_carousel(url, info)
                if cls._is_all_videos_carousel(info):
                    return await download_video_carousel(url, info)
                return await cls._download_mixed_carousel(url, info)
            if cls._is_image_post(info):
                return await download_post_image(url, info)
            return await download_post_video(url, info)
        if re.search(r"instagram\.com/reels?/", url, re.IGNORECASE):
            logger.warning("[Instagram Post] yt-dlp failed for reel")
            raise DownloadError("Could not extract reel video data", platform="instagram", retryable=True)
        logger.info("[Instagram Post] yt-dlp returned no data, trying HTTP fallback for images")
        return await download_post_image_via_http(url)
