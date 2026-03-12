"""TikTok media downloader — downloads videos and images directly into memory."""

import asyncio
import json
import re

from loguru import logger

from src.downloaders.base_downloader import (
    BaseDownloader,
    DownloadResult,
    DownloadError,
)
from src.downloaders.tiktok_image_download import (
    download_images_from_info,
    download_images_via_scrape,
)
from src.downloaders.tiktok_video_download import download_video


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

        try:
            info = await self._extract_info(url)
            if self._is_image_post(info):
                return await download_images_from_info(url, info)
            return await download_video(url, info)
        except DownloadError as e:
            if "Unsupported URL" in e.message or "no video" in e.message.lower():
                logger.info(
                    "[TikTok] yt-dlp failed, trying HTTP scrape fallback for images"
                )
                return await download_images_via_scrape(url)
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
