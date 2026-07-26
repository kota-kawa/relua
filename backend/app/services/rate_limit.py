from functools import lru_cache

from redis import Redis
from redis.exceptions import RedisError

from app.config import get_settings


class RateLimitUnavailable(Exception):
    pass


class RateLimitExceeded(Exception):
    pass


@lru_cache
def redis_client() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True, socket_connect_timeout=1)


def enforce_rate_limit(client_name: str, operation: str) -> None:
    key = f"mcp-rate:{client_name}:{operation}"
    try:
        value = redis_client().incr(key)
        if value == 1:
            redis_client().expire(key, 60)
        if value > get_settings().mcp_rate_limit_per_minute:
            raise RateLimitExceeded
    except RateLimitExceeded:
        raise
    except RedisError as exc:
        raise RateLimitUnavailable from exc


def register_validation_failure(client_name: str, request_id: str) -> int:
    key = f"mcp-validation:{client_name}:{request_id}"
    try:
        value = int(redis_client().incr(key))
        redis_client().expire(key, 3600)
        return value
    except RedisError:
        return 1
