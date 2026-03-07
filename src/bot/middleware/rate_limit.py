"""In-memory rate limiting using dict + TTL."""

import time
from collections import defaultdict

from loguru import logger

from src.config.settings import settings


# In-memory rate limit tracker: {user_id: [timestamp, ...]}
# Resets on bot restart (stateless design)
_user_requests: dict[int, list[float]] = defaultdict(list)


def is_rate_limited(user_id: int) -> bool:
    """Check if a user has exceeded the rate limit.

    Args:
        user_id: Telegram user ID.

    Returns:
        True if rate limited, False otherwise.
    """
    now = time.time()
    max_per_min = settings.rate_limit_per_min

    # Clean old entries (older than 60 seconds)
    _user_requests[user_id] = [
        t for t in _user_requests[user_id] if now - t < 60
    ]

    if len(_user_requests[user_id]) >= max_per_min:
        logger.warning(f"User {user_id} rate limited ({max_per_min}/min)")
        return True

    _user_requests[user_id].append(now)
    return False


def get_remaining_requests(user_id: int) -> int:
    """Get remaining requests for a user in the current window."""
    now = time.time()
    _user_requests[user_id] = [
        t for t in _user_requests[user_id] if now - t < 60
    ]
    return max(0, settings.rate_limit_per_min - len(_user_requests[user_id]))
