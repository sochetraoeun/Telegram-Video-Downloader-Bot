"""YouTube Shorts download logic — short-form vertical videos via yt-dlp."""

import io
import asyncio

from loguru import logger

from src.downloaders.base_downloader import (
    DownloadResult,
    DownloadError,
    MediaType,
)


async def download_short(
    url: str, info: dict, cookie_args: list[str] | None = None
) -> DownloadResult:
    """Download a YouTube Short into memory.

    Shorts are typically short vertical videos, so we use a simpler
    format selector optimized for quick downloads.
    """
    title = info.get("title") or info.get("fulltitle")
    duration = info.get("duration")
    width = info.get("width")
    height = info.get("height")

    try:
        cmd = [
            "yt-dlp",
            "--no-warnings",
            "--no-check-certificates",
            "--format",
            "bestvideo[filesize<50M]+bestaudio/best[filesize<50M]/best",
            "--merge-output-format",
            "mp4",
            "--output",
            "-",
            "--quiet",
            *(cookie_args or []),
            url,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
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
                platform="youtube",
            )

        if not stdout:
            raise DownloadError(
                "No video data received",
                platform="youtube",
            )

        buffer = io.BytesIO(stdout)
        file_size = len(stdout)
        buffer.seek(0)

        logger.info(
            f"[YouTube] Downloaded Short: {file_size / 1024 / 1024:.1f} MB"
        )

        return DownloadResult(
            buffer=buffer,
            filename="youtube_short.mp4",
            file_size=file_size,
            media_type=MediaType.VIDEO,
            caption=title,
            duration=duration,
            width=width,
            height=height,
        )

    except asyncio.TimeoutError:
        raise DownloadError(
            "Download timed out (>120s)", platform="youtube"
        )
    except DownloadError:
        raise
    except Exception as e:
        raise DownloadError(f"Unexpected error: {e}", platform="youtube")
