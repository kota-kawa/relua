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


def _fixed_window(key: str, limit: int, window_seconds: int) -> None:
    """Count one hit in a fixed window and refuse once the limit is passed.

    A Redis outage raises RateLimitUnavailable rather than passing the call through. The callers guard
    login and client-registration attempts, where losing the limiter is worse than refusing the request.
    """
    try:
        value = redis_client().incr(key)
        if value == 1:
            redis_client().expire(key, window_seconds)
        if value > limit:
            raise RateLimitExceeded
    except RateLimitExceeded:
        raise
    except RedisError as exc:
        raise RateLimitUnavailable from exc


def enforce_login_rate_limit(identifier: str) -> None:
    _fixed_window(f"mcp-login:{identifier}", get_settings().mcp_login_rate_limit_per_minute, 60)


def clear_login_rate_limit(identifier: str) -> None:
    try:
        redis_client().delete(f"mcp-login:{identifier}")
    except RedisError:
        pass


def enforce_registration_rate_limit(identifier: str) -> None:
    _fixed_window(f"mcp-register:{identifier}", get_settings().mcp_registration_rate_limit_per_hour, 3600)


def register_validation_failure(client_name: str, request_id: str) -> int:
    key = f"mcp-validation:{client_name}:{request_id}"
    try:
        value = int(redis_client().incr(key))
        redis_client().expire(key, 3600)
        return value
    except RedisError:
        return 1
