"""Request logging middleware."""

from loguru import logger
from telegram import Update
from telegram.ext import ContextTypes


async def log_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log incoming updates for debugging/monitoring."""
    if update.message:
        user = update.message.from_user
        chat = update.message.chat
        text = update.message.text or "[non-text]"

        logger.info(
            f"[MSG] user={user.id}(@{user.username}) "
            f"chat={chat.id}({chat.type}) "
            f"text={text[:100]}"
        )
    elif update.callback_query:
        user = update.callback_query.from_user
        data = update.callback_query.data
        logger.info(f"[CALLBACK] user={user.id}(@{user.username}) data={data}")
