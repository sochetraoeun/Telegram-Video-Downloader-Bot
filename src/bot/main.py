"""Bot entry point — initializes and runs the Telegram bot."""

import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
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


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (stdlib API)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args) -> None:  # silence default stdout logs
        return


def start_health_server() -> None:
    """Start a tiny HTTP server so hosts like Render (Web Service) pass their port scan.

    Reads PORT from env (Render sets this). No-op if PORT is not set (local runs).
    """
    port_str = os.environ.get("PORT")
    if not port_str:
        return
    try:
        port = int(port_str)
    except ValueError:
        logger.warning(f"Invalid PORT value: {port_str!r}; skipping health server")
        return

    server = HTTPServer(("0.0.0.0", port), _HealthHandler)

    thread = threading.Thread(
        target=server.serve_forever, name="health-server", daemon=True
    )
    thread.start()
    logger.info(f"🩺 Health server listening on 0.0.0.0:{port} (GET / → 200 ok)")


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

    start_health_server()

    app = create_bot()

    logger.info("🟢 Bot is now running! Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
