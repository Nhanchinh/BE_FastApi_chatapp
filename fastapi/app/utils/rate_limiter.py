from slowapi import Limiter
from slowapi.util import get_remote_address


# Global limiter instance shared across the app
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])


def limit_per_minute(rate: str):
    """
    Helper decorator to apply custom rate limit.
    Usage: @limit_per_minute("10/minute")
    """

    return limiter.limit(rate)

