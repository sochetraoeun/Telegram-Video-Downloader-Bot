"""YouTube video download logic — regular videos via yt-dlp."""

import io
import asyncio

from loguru import logger

from src.downloaders.base_downloader import (
    DownloadResult,
    DownloadError,
    MediaType,
)


async def download_video(url: str, info: dict) -> DownloadResult:
    """Download a regular YouTube video into memory.

    Uses yt-dlp with best merged format capped at 50MB,
    falling back to best single-stream format.
    """
    title = info.get("title") or info.get("fulltitle")
    duration = info.get("duration")
    width = info.get("width")
    height = info.get("height")

    try:
        process = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--no-warnings",
            "--no-check-certificates",
            "--format",
            "bestvideo[filesize<50M]+bestaudio/best[filesize<50M]/bestvideo+bestaudio/best",
            "--merge-output-format",
            "mp4",
            "--output",
            "-",
            "--quiet",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=300
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
            f"[YouTube] Downloaded video: {file_size / 1024 / 1024:.1f} MB"
        )

        return DownloadResult(
            buffer=buffer,
            filename="youtube_video.mp4",
            file_size=file_size,
            media_type=MediaType.VIDEO,
            caption=title,
            duration=duration,
            width=width,
            height=height,
        )

    except asyncio.TimeoutError:
        raise DownloadError(
            "Download timed out (>300s)", platform="youtube"
        )
    except DownloadError:
        raise
    except Exception as e:
        raise DownloadError(f"Unexpected error: {e}", platform="youtube")
