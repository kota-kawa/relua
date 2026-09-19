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


#: Returned by the API layer when the reverse proxy did not hand us a usable peer address.
UNRESOLVED_CLIENT_IP = "unknown"

#: How much slack the wider login buckets get over the per-IP one. The per-IP bucket is the precise
#: limit; these two are ceilings that still hold when the address cannot be trusted, so they are
#: deliberately loose enough that ordinary operator retries never reach them.
CLIENT_LOGIN_LIMIT_MULTIPLIER = 4
GLOBAL_LOGIN_LIMIT_MULTIPLIER = 20


def _fixed_window(key: str, limit: int, window_seconds: int) -> None:
    """Count one hit in a fixed window and refuse once the limit is passed.

    INCR and EXPIRE go out as one pipeline instead of two calls. Issuing EXPIRE only when the counter
    came back as 1 meant a crash or a dropped connection in between left the key with no TTL at all,
    and that bucket then stayed over the limit forever — a permanent lockout that only a manual DEL
    could clear. ``EXPIRE ... NX`` is idempotent, so replaying it on every hit is safe and keeps the
    window anchored to the first hit rather than sliding forward.

    A Redis outage raises RateLimitUnavailable rather than passing the call through. The callers guard
    login and client-registration attempts, where losing the limiter is worse than refusing the request.
    """
    try:
        pipeline = redis_client().pipeline(transaction=True)
        pipeline.incr(key)
        pipeline.expire(key, window_seconds, nx=True)
        value = int(pipeline.execute()[0])
    except RedisError as exc:
        raise RateLimitUnavailable from exc
    if value > limit:
        raise RateLimitExceeded


def _login_keys(identifier: str | None, client_id: str | None) -> list[tuple[str, int]]:
    """The login buckets to count a single attempt against, narrowest first.

    A per-IP bucket alone is only as good as the address the proxy hands us. Behind the reverse proxy
    every request can arrive from the same docker bridge gateway, and then one shared bucket lets an
    attacker spend the operator's five attempts and lock them out; conversely, a spoofable
    X-Forwarded-For makes the bucket key attacker-chosen and the limit meaningless.

    So the buckets are chosen by how much the identifier can be trusted. A resolved address gets its
    own precise bucket plus the per-client ceiling, and nothing wider: a server-wide counter that
    every request shares would be a lockout switch, because an attacker rotating through a couple of
    dozen addresses (trivial on IPv6) could spend it and the operator's own next attempt would be
    refused along with theirs. Distributed guessing is instead bounded by the password itself, which
    config.py already refuses to let default. An unresolved address skips the per-IP bucket — its key
    would be shared or attacker-chosen — and falls back to the server-wide ceiling, which is the only
    thing left to bound it. Narrowest first matters: one hot address exhausts its own budget and stops
    there instead of eating into the shared ceilings.
    """
    limit = get_settings().mcp_login_rate_limit_per_minute
    keys: list[tuple[str, int]] = []
    resolved = bool(identifier) and identifier != UNRESOLVED_CLIENT_IP
    if resolved:
        keys.append((f"mcp-login:{identifier}", limit))
    if client_id:
        keys.append((f"mcp-login-client:{client_id}", limit * CLIENT_LOGIN_LIMIT_MULTIPLIER))
    if not resolved:
        keys.append(("mcp-login:all", limit * GLOBAL_LOGIN_LIMIT_MULTIPLIER))
    return keys


def enforce_login_rate_limit(identifier: str | None, client_id: str | None = None) -> None:
    for key, limit in _login_keys(identifier, client_id):
        _fixed_window(key, limit, 60)


def clear_login_rate_limit(identifier: str | None, client_id: str | None = None) -> None:
    """Give a successful login its budget back, including the shared ceilings it spent."""
    try:
        redis_client().delete(*(key for key, _ in _login_keys(identifier, client_id)))
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
