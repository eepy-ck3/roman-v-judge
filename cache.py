"""
cache.py — Lightweight in-memory TTL cache.

No Redis, no Memcached, no fuss. Just a dict with timestamps.
Prevents hammering the MLB API and blowing through The Odds API free tier.
"""
import time
import functools
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

_store: dict[str, tuple[Any, float]] = {}


def cached(ttl: int = 900):
    """
    Decorator that caches a function's return value for `ttl` seconds.
    Won't cache None returns (which usually mean an API error).

    Usage:
        @cached(ttl=300)
        def get_player_stats(player_id):
            ...
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = f"{func.__module__}.{func.__name__}|{args}|{sorted(kwargs.items())}"
            now = time.time()

            if key in _store:
                result, ts = _store[key]
                age = now - ts
                if age < ttl:
                    logger.debug(f"Cache HIT [{func.__name__}] — {int(age)}s old")
                    return result

            logger.debug(f"Cache MISS [{func.__name__}] — fetching fresh")
            result = func(*args, **kwargs)
            if result is not None:
                _store[key] = (result, now)
            return result
        return wrapper
    return decorator


def invalidate(prefix: str = ""):
    """Clear cache entries matching a prefix. Pass '' to nuke everything."""
    keys_to_delete = [k for k in _store if prefix in k]
    for k in keys_to_delete:
        del _store[k]
    logger.info(f"Cache invalidated {len(keys_to_delete)} entries (prefix='{prefix}')")


def stats() -> dict:
    """Debugging endpoint — see what's in the cache and how old it is."""
    now = time.time()
    return {
        "total_entries": len(_store),
        "entries": [
            {"key": k[:80], "age_seconds": int(now - ts)}
            for k, (_, ts) in sorted(_store.items(), key=lambda x: x[1][1])
        ]
    }
