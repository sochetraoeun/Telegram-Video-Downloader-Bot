"""Bot entry point — initializes and runs the Telegram bot."""

import sys
from pathlib import Path

from loguru import logger
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.config.settings import settings
from src.bot.handlers.command_handler import start_command, help_command, audio_command
from src.bot.handlers.message_handler import handle_message


def setup_logging() -> None:
    """Configure loguru logging."""
    logger.remove()  # Remove default handler
    logger.add(
        sys.stderr,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        level="INFO",
        colorize=True,
    )
    logger.info("Logging configured ✅")


def create_bot():
    """Create and configure the bot application."""
    logger.info("🤖 Initializing Telegram Video Downloader Bot...")
    logger.info(f"📌 Supported platforms: {settings.platforms_list}")

    app = ApplicationBuilder().token(settings.bot_token).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("audio", audio_command))

    # Register message handler (for link detection)
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    logger.info("✅ Bot handlers registered")
    return app


def main() -> None:
    """Main entry point."""
    setup_logging()

    logger.info("=" * 50)
    logger.info("🚀 Starting Telegram Video Downloader Bot")
    logger.info(f"📊 Rate limit: {settings.rate_limit_per_min}/min")
    logger.info(f"📦 Max file size: {settings.max_file_size_mb}MB")
    logger.info(f"🔄 Max retries: {settings.max_retry_attempts}")
    logger.info(f"⚡ Max concurrent: {settings.max_concurrent_downloads}")
    logger.info("=" * 50)

    app = create_bot()

    logger.info("🟢 Bot is now running! Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
