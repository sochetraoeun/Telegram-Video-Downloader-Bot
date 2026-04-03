"""Command handlers for /start, /help, /audio."""

from loguru import logger
from telegram import Update
from telegram.ext import ContextTypes

from src.utils.constants import WELCOME_MESSAGE, HELP_MESSAGE
from src.utils.url_parser import extract_supported_urls
from src.utils.formatter import format_file_size, format_success_message
from src.bot.reactions.reactor import react
from src.downloaders.base_downloader import DownloadError, MediaType
from src.downloaders.youtube_downloader import YouTubeDownloader
from src.downloaders.instagram_downloader import InstagramDownloader
from src.services.video_service import free_result


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    if not update.message:
        return

    logger.info(f"[CMD] /start from user {update.message.from_user.id}")
    await react(update, "welcome")
    await update.message.reply_text(
        WELCOME_MESSAGE,
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command."""
    if not update.message:
        return

    logger.info(f"[CMD] /help from user {update.message.from_user.id}")
    await update.message.reply_text(
        HELP_MESSAGE,
        parse_mode="Markdown",
    )


async def audio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /audio command — extract audio from YouTube or Instagram video as MP3."""
    if not update.message:
        return

    logger.info(f"[CMD] /audio from user {update.message.from_user.id}")

    text = update.message.text.replace("/audio", "", 1).strip()

    if not text:
        await update.message.reply_text(
            "🎵 **Audio Extraction**\n\n"
            "Send a **YouTube** or **Instagram** video link after the command:\n"
            "`/audio https://www.youtube.com/watch?v=...`\n"
            "`/audio https://www.instagram.com/reel/...`\n\n"
            "I'll extract the audio and send it as MP3!",
            parse_mode="Markdown",
        )
        return

    urls = extract_supported_urls(text)
    audio_urls = [(url, p) for url, p in urls if p in ("youtube", "instagram")]

    if not audio_urls:
        await update.message.reply_text(
            "❌ Please provide a valid YouTube or Instagram video link.\n"
            "Examples:\n"
            "`/audio https://www.youtube.com/watch?v=dQw4w9WgXcQ`\n"
            "`/audio https://www.instagram.com/reel/...`",
            parse_mode="Markdown",
        )
        return

    url, platform = audio_urls[0]
    await react(update, "processing")

    status_msg = await update.message.reply_text(
        f"🎵 Extracting audio from **{platform.title()}**...",
        parse_mode="Markdown",
    )

    result = None
    try:
        if platform == "youtube":
            result = await YouTubeDownloader().download(url, audio_only=True)
        else:
            result = await InstagramDownloader().download(url, audio_only=True)

        try:
            await status_msg.edit_text(
                f"📤 Uploading **{format_file_size(result.file_size)}** audio...",
                parse_mode="Markdown",
            )
        except Exception:
            pass

        await context.bot.send_audio(
            chat_id=update.message.chat_id,
            audio=result.buffer,
            filename=result.filename,
            caption=format_success_message(result.media_type, result.caption),
            parse_mode="Markdown",
            duration=result.duration,
            title=result.caption,
        )

        await react(update, "complete")

        try:
            await status_msg.delete()
        except Exception:
            pass

    except DownloadError as e:
        await react(update, "error")
        try:
            await status_msg.edit_text(f"❌ {e.message}")
        except Exception:
            await update.message.reply_text(f"❌ {e.message}")

    except Exception as e:
        await react(update, "error")
        try:
            await status_msg.edit_text("❌ Failed to extract audio. Please try again.")
        except Exception:
            await update.message.reply_text("❌ Failed to extract audio. Please try again.")
        logger.exception(f"Audio extraction failed: {e}")

    finally:
        if result:
            free_result(result)
