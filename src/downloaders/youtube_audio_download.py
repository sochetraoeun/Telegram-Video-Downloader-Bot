"""YouTube audio extraction — convert to MP3 via yt-dlp + ffmpeg."""

import io
import os
import asyncio
import glob
import tempfile

from loguru import logger

from src.downloaders.base_downloader import (
    DownloadResult,
    DownloadError,
    MediaType,
)


async def download_audio(
    url: str, info: dict, cookie_args: list[str] | None = None
) -> DownloadResult:
    """Extract audio from a YouTube video and return as MP3.

    Downloads to a temp file first since yt-dlp audio extraction with
    ffmpeg post-processing requires seekable output.
    """
    title = info.get("title") or info.get("fulltitle")
    duration = info.get("duration")

    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="yt_audio_")
        output_template = os.path.join(tmp_dir, "audio.%(ext)s")

        cmd = [
            "yt-dlp",
            "--no-warnings",
            "--no-check-certificates",
            "--no-playlist",
            "--extract-audio",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "--output",
            output_template,
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
                f"Audio extraction failed: {error_msg}",
                platform="youtube",
            )

        mp3_files = glob.glob(os.path.join(tmp_dir, "*.mp3"))
        if not mp3_files:
            all_files = glob.glob(os.path.join(tmp_dir, "*"))
            if all_files:
                mp3_files = all_files
            else:
                raise DownloadError(
                    "No audio data received",
                    platform="youtube",
                )

        audio_path = mp3_files[0]

        with open(audio_path, "rb") as f:
            data = f.read()

        buffer = io.BytesIO(data)
        file_size = len(data)
        buffer.seek(0)

        safe_title = (title or "youtube_audio").replace("/", "_")[:60]

        logger.info(
            f"[YouTube] Extracted audio: {file_size / 1024 / 1024:.1f} MB"
        )

        return DownloadResult(
            buffer=buffer,
            filename=f"{safe_title}.mp3",
            file_size=file_size,
            media_type=MediaType.AUDIO,
            caption=title,
            duration=duration,
        )

    except asyncio.TimeoutError:
        raise DownloadError(
            "Audio extraction timed out (>300s)", platform="youtube"
        )
    except DownloadError:
        raise
    except Exception as e:
        raise DownloadError(f"Unexpected error: {e}", platform="youtube")
    finally:
        if tmp_dir and os.path.exists(tmp_dir):
            for f in glob.glob(os.path.join(tmp_dir, "*")):
                try:
                    os.unlink(f)
                except OSError:
                    pass
            try:
                os.rmdir(tmp_dir)
            except OSError:
                pass
