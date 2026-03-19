"""YouTube video download logic — regular videos via yt-dlp."""

import io
import os
import asyncio
import tempfile

from loguru import logger

from src.downloaders.base_downloader import (
    DownloadResult,
    DownloadError,
    MediaType,
)


async def download_video(
    url: str, info: dict, cookie_args: list[str] | None = None
) -> DownloadResult:
    """Download a regular YouTube video into memory.

    Downloads to a temp file first (required for ffmpeg muxing of
    separate video+audio streams), then reads into BytesIO.
    """
    title = info.get("title") or info.get("fulltitle")
    duration = info.get("duration")
    width = info.get("width")
    height = info.get("height")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name

        cmd = [
            "yt-dlp",
            "--no-warnings",
            "--no-check-certificates",
            "--no-playlist",
            "--format",
            "bestvideo[filesize<50M]+bestaudio/best[filesize<50M]/bestvideo+bestaudio/best",
            "--merge-output-format",
            "mp4",
            "--output",
            tmp_path,
            "--force-overwrites",
            "--quiet",
            *(cookie_args or []),
            url,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await asyncio.wait_for(
            process.communicate(), timeout=300
        )

        if process.returncode != 0:
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            raise DownloadError(
                f"yt-dlp failed: {error_msg}",
                platform="youtube",
            )

        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            raise DownloadError(
                "No video data received",
                platform="youtube",
            )

        with open(tmp_path, "rb") as f:
            data = f.read()

        buffer = io.BytesIO(data)
        file_size = len(data)
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
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
