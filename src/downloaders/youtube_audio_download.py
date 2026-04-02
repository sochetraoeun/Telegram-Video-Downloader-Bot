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

_AUDIO_FORMAT_PRIORITIES = [
    "bestaudio[ext=m4a]/bestaudio",
    "bestaudio/best",
    "worstaudio",
]


def _cleanup_tmp_dir(tmp_dir: str) -> None:
    """Remove temp directory and all files inside it."""
    for f in glob.glob(os.path.join(tmp_dir, "*")):
        try:
            os.unlink(f)
        except OSError:
            pass
    try:
        os.rmdir(tmp_dir)
    except OSError:
        pass


async def download_audio(
    url: str,
    info: dict,
    cookie_args: list[str] | None = None,
    player_clients: str = "ios,web",
) -> DownloadResult:
    """Extract audio from a YouTube video and return as MP3.

    Tries multiple audio format strings for resilience. Downloads to a
    temp dir since yt-dlp audio extraction with ffmpeg post-processing
    requires seekable output.
    """
    title = info.get("title") or info.get("fulltitle")
    duration = info.get("duration")

    last_error: str = ""
    for fmt in _AUDIO_FORMAT_PRIORITIES:
        tmp_dir = None
        try:
            tmp_dir = tempfile.mkdtemp(prefix="yt_audio_")
            output_template = os.path.join(tmp_dir, "audio.%(ext)s")

            cmd = [
                "yt-dlp",
                "--no-warnings",
                "--no-check-certificates",
                "--no-playlist",
                "--extractor-args", f"youtube:player_client={player_clients}",
                "--format", fmt,
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", "0",
                "--output", output_template,
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
                logger.debug(f"[YouTube] Audio format '{fmt}' failed: {last_error}")
                continue

            mp3_files = glob.glob(os.path.join(tmp_dir, "*.mp3"))
            if not mp3_files:
                all_files = glob.glob(os.path.join(tmp_dir, "*"))
                if all_files:
                    mp3_files = all_files
                else:
                    logger.debug(f"[YouTube] Audio format '{fmt}' produced no files")
                    continue

            audio_path = mp3_files[0]

            with open(audio_path, "rb") as f:
                data = f.read()

            buffer = io.BytesIO(data)
            file_size = len(data)
            buffer.seek(0)

            safe_title = (title or "youtube_audio").replace("/", "_")[:60]

            logger.info(
                f"[YouTube] Extracted audio: {file_size / 1024 / 1024:.1f} MB (format: {fmt})"
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
            last_error = str(e)
            logger.debug(f"[YouTube] Audio format '{fmt}' exception: {e}")
            continue
        finally:
            if tmp_dir and os.path.exists(tmp_dir):
                _cleanup_tmp_dir(tmp_dir)

    raise DownloadError(
        f"All audio format attempts failed. Last error: {last_error}",
        platform="youtube",
    )
