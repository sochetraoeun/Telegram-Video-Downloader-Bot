"""YouTube media downloader — orchestrates video, Shorts, and audio downloads."""

import asyncio
import json
import re

from loguru import logger

from src.downloaders.base_downloader import (
    BaseDownloader,
    DownloadResult,
    DownloadError,
)
from src.downloaders.youtube_video_download import download_video
from src.downloaders.youtube_shorts_download import download_short
from src.downloaders.youtube_audio_download import download_audio

_SHORTS_PATTERN = re.compile(
    r"https?://(www\.)?youtube\.com/shorts/[\w-]+", re.IGNORECASE
)


class YouTubeDownloader(BaseDownloader):
    """Downloads YouTube videos, Shorts, and optionally extracts audio."""

    platform = "youtube"

    async def supports(self, url: str) -> bool:
        patterns = [
            r"https?://(www\.)?youtube\.com/watch\?v=[\w-]+",
            r"https?://(www\.)?youtube\.com/shorts/[\w-]+",
            r"https?://youtu\.be/[\w-]+",
            r"https?://(www\.)?youtube\.com/embed/[\w-]+",
            r"https?://(www\.)?youtube\.com/live/[\w-]+",
            r"https?://m\.youtube\.com/watch\?v=[\w-]+",
        ]
        return any(
            re.match(p, url, re.IGNORECASE) for p in patterns
        )

    async def download(self, url: str, audio_only: bool = False) -> DownloadResult:
        """Download YouTube media (video, Short, or audio) into memory."""
        logger.info(f"[YouTube] Downloading: {url}")

        info = await self._extract_info(url)

        if audio_only:
            logger.info("[YouTube] Audio-only mode requested")
            return await download_audio(url, info)

        if self._is_shorts(url):
            logger.info("[YouTube] Detected Shorts URL")
            return await download_short(url, info)

        return await download_video(url, info)

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

                if any(k in error_msg.lower() for k in ("private", "unavailable", "removed")):
                    raise DownloadError(
                        "This video is private, unavailable, or has been removed",
                        platform=self.platform,
                        retryable=False,
                    )
                if "sign in" in error_msg.lower() or "age" in error_msg.lower():
                    raise DownloadError(
                        "This video requires sign-in or is age-restricted",
                        platform=self.platform,
                        retryable=False,
                    )

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
                "Failed to parse video info",
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

    def _is_shorts(self, url: str) -> bool:
        """Detect if the URL is a YouTube Shorts link."""
        return bool(_SHORTS_PATTERN.match(url))
