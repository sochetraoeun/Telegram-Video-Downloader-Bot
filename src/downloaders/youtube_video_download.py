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

_FORMAT_PRIORITIES = [
    "bestvideo[filesize<50M][ext=mp4]+bestaudio[ext=m4a]/bestvideo[filesize<50M]+bestaudio",
    "bestvideo+bestaudio/best",
    "best[filesize<50M]/best",
    "18/22",
]


async def download_video(
    url: str,
    info: dict,
    cookie_args: list[str] | None = None,
    player_clients: str = "ios,web",
) -> DownloadResult:
    """Download a regular YouTube video into memory.

    Tries multiple format strings for resilience. Downloads to a temp file
    first (required for ffmpeg muxing of separate video+audio streams),
    then reads into BytesIO.
    """
    title = info.get("title") or info.get("fulltitle")
    duration = info.get("duration")
    width = info.get("width")
    height = info.get("height")

    last_error: str = ""
    for fmt in _FORMAT_PRIORITIES:
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                tmp_path = tmp.name

            cmd = [
                "yt-dlp",
                "--no-warnings",
                "--no-check-certificates",
                "--no-playlist",
                "--extractor-args", f"youtube:player_client={player_clients}",
                "--format", fmt,
                "--merge-output-format", "mp4",
                "--output", tmp_path,
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
                last_error = stderr.decode().strip() if stderr else "Unknown error"
                logger.debug(f"[YouTube] Format '{fmt}' failed: {last_error}")
                continue

            if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                logger.debug(f"[YouTube] Format '{fmt}' produced empty file")
                continue

            with open(tmp_path, "rb") as f:
                data = f.read()

            buffer = io.BytesIO(data)
            file_size = len(data)
            buffer.seek(0)

            logger.info(
                f"[YouTube] Downloaded video: {file_size / 1024 / 1024:.1f} MB (format: {fmt})"
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
            last_error = str(e)
            logger.debug(f"[YouTube] Format '{fmt}' exception: {e}")
            continue
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    raise DownloadError(
        f"All format attempts failed. Last error: {last_error}",
        platform="youtube",
    )
