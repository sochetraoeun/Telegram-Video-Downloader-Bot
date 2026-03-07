"""Command handlers for /start, /help, /audio."""

from loguru import logger
from telegram import Update
from telegram.ext import ContextTypes

from src.utils.constants import WELCOME_MESSAGE, HELP_MESSAGE
from src.bot.reactions.reactor import react


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
    """Handle the /audio command — extract audio from video link."""
    if not update.message:
        return

    logger.info(f"[CMD] /audio from user {update.message.from_user.id}")

    # TODO: Implement audio extraction in Phase 2
    await update.message.reply_text(
        "🎵 Audio extraction is coming soon! Stay tuned. 🚧",
        parse_mode="Markdown",
    )
