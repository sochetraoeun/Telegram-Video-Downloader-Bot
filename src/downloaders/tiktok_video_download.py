"""TikTok video download logic — single video download via yt-dlp."""

import io
import asyncio

from loguru import logger

from src.downloaders.base_downloader import (
    DownloadResult,
    DownloadError,
    MediaType,
)


async def download_video(url: str, info: dict) -> DownloadResult:
    """Download video bytes into memory."""
    try:
        process = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--no-warnings",
            "--no-check-certificates",
            "--format",
            "best[filesize<50M]/best",
            "--output",
            "-",
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
                platform="tiktok",
            )

        if not stdout:
            raise DownloadError(
                "No video data received",
                platform="tiktok",
            )

        buffer = io.BytesIO(stdout)
        file_size = len(stdout)
        buffer.seek(0)

        logger.info(
            f"[TikTok] Downloaded video: {file_size / 1024 / 1024:.1f} MB"
        )

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
        raise DownloadError(
            "Download timed out (>120s)", platform="tiktok"
        )
    except DownloadError:
        raise
    except Exception as e:
        raise DownloadError(f"Unexpected error: {e}", platform="tiktok")
