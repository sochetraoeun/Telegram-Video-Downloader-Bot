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
from src.config.settings import settings

_SHORTS_PATTERN = re.compile(
    r"https?://(www\.)?youtube\.com/shorts/[\w-]+", re.IGNORECASE
)

_PLAYER_CLIENT_STRATEGIES = [
    "ios,web",
    "android,web",
    "tv,ios",
    "default",
]


def _get_cookie_args() -> list[str]:
    """Build yt-dlp cookie arguments if YouTube cookies are configured."""
    if settings.youtube_cookies_file:
        return ["--cookies", settings.youtube_cookies_file]
    return []


def _get_base_args(player_clients: str = "ios,web") -> list[str]:
    """Common yt-dlp arguments that help bypass bot detection without cookies."""
    args = [
        "yt-dlp",
        "--no-warnings",
        "--no-check-certificates",
        "--no-playlist",
        "--extractor-args", f"youtube:player_client={player_clients}",
    ]
    return args


def _is_bot_or_auth_error(error_msg: str) -> bool:
    """Check if the error indicates bot detection or auth requirement."""
    err_lower = error_msg.lower()
    bot_keywords = [
        "sign in", "confirm your age", "bot", "verify",
        "please sign in", "login required", "authentication",
        "consent", "cookies",
    ]
    return any(k in err_lower for k in bot_keywords)


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
        """Download YouTube media (video, Short, or audio) into memory.

        Tries multiple player-client strategies to bypass bot detection
        without requiring cookies.
        """
        logger.info(f"[YouTube] Downloading: {url}")

        cookie_args = _get_cookie_args()
        last_error: Exception | None = None

        for strategy in _PLAYER_CLIENT_STRATEGIES:
            try:
                logger.debug(f"[YouTube] Trying player_client={strategy}")
                info = await self._extract_info(url, cookie_args, player_clients=strategy)

                if audio_only:
                    logger.info("[YouTube] Audio-only mode requested")
                    return await download_audio(url, info, cookie_args, player_clients=strategy)

                if self._is_shorts(url):
                    logger.info("[YouTube] Detected Shorts URL")
                    return await download_short(url, info, cookie_args, player_clients=strategy)

                return await download_video(url, info, cookie_args, player_clients=strategy)

            except DownloadError as e:
                last_error = e
                if not e.retryable:
                    if _is_bot_or_auth_error(e.message) and strategy != _PLAYER_CLIENT_STRATEGIES[-1]:
                        logger.warning(
                            f"[YouTube] Strategy {strategy} hit bot detection, trying next..."
                        )
                        continue
                    raise
                logger.warning(f"[YouTube] Strategy {strategy} failed: {e.message}")
                continue

        raise last_error or DownloadError(
            "All YouTube download strategies failed",
            platform=self.platform,
            retryable=False,
        )

    async def _extract_info(
        self,
        url: str,
        cookie_args: list[str],
        player_clients: str = "ios,web",
    ) -> dict:
        """Extract metadata with yt-dlp --dump-json."""
        try:
            cmd = [
                *_get_base_args(player_clients),
                "--dump-json",
                "--quiet",
                *cookie_args,
                url,
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=60
            )

            if process.returncode != 0:
                error_msg = stderr.decode().strip() if stderr else "Unknown error"
                err_lower = error_msg.lower()

                if any(k in err_lower for k in ("private video", "video is private")):
                    raise DownloadError(
                        "This video is private",
                        platform=self.platform,
                        retryable=False,
                    )
                if "has been removed" in err_lower or "video is unavailable" in err_lower:
                    raise DownloadError(
                        "This video has been removed or is unavailable",
                        platform=self.platform,
                        retryable=False,
                    )
                if "age" in err_lower and "restrict" in err_lower:
                    raise DownloadError(
                        "This video is age-restricted. "
                        "Try a different video, or set YOUTUBE_COOKIES_FILE for age-restricted content.",
                        platform=self.platform,
                        retryable=False,
                    )
                if _is_bot_or_auth_error(error_msg):
                    raise DownloadError(
                        f"YouTube bot detection triggered (player_client={player_clients})",
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
                "Info extraction timed out (>60s)",
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
