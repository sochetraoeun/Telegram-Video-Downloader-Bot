"""Emoji reaction logic for human-like bot behavior."""

from loguru import logger
from telegram import Update


# Reaction emoji mapping
REACTIONS = {
    "processing": "⏳",
    "downloading": "📥",
    "complete": "✅",
    "error": "❌",
    "thanks": "❤️",
    "welcome": "👋",
}


async def react(update: Update, reaction_type: str) -> None:
    """React to a message with an emoji.

    Args:
        update: The Telegram update containing the message.
        reaction_type: One of the REACTIONS keys.
    """
    if not update.message:
        return

    emoji = REACTIONS.get(reaction_type)
    if not emoji:
        return

    try:
        await update.message.set_reaction(emoji)
    except Exception as e:
        # Reactions may not be supported in all chat types
        logger.debug(f"Could not set reaction '{emoji}': {e}")


async def check_thanks(text: str) -> bool:
    """Check if a message is a 'thank you' message."""
    thanks_keywords = [
        "thank", "thanks", "thx", "ty",
        "អរគុណ", "អរ​គុណ",  # Khmer: thank you
        "🙏", "❤️",
    ]
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in thanks_keywords)
