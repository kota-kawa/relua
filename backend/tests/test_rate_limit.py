"""Brute-force protection for the operator login.

The endpoint tests replace these functions with no-ops so the OAuth flow can be exercised without a
Redis, which leaves the limiter itself untested. These tests drive it directly against a fake Redis so
the counting, the expiry and the fail-closed behaviour are all covered.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app.api import oauth as oauth_api
from app.db import get_db
from app.models import OAuthClient
from app.services import rate_limit
from app.services.rate_limit import (
    CLIENT_LOGIN_LIMIT_MULTIPLIER,
    GLOBAL_LOGIN_LIMIT_MULTIPLIER,
    UNRESOLVED_CLIENT_IP,
    RateLimitExceeded,
    RateLimitUnavailable,
    clear_login_rate_limit,
    enforce_login_rate_limit,
    enforce_registration_rate_limit,
)

LIMIT = 5
#: Matches the mcp_registration_rate_limit_per_hour default the settings fixture leaves in place.
REGISTRATION_LIMIT = 20


class FakePipeline:
    """Just enough of redis-py's pipeline to record INCR and EXPIRE NX in one execute()."""

    def __init__(self, redis: "FakeRedis") -> None:
        self.redis = redis
        self.commands: list[tuple] = []

    def incr(self, key: str) -> "FakePipeline":
        self.commands.append(("incr", key))
        return self

    def expire(self, key: str, seconds: int, nx: bool = False) -> "FakePipeline":
        self.commands.append(("expire", key, seconds, nx))
        return self

    def execute(self) -> list:
        if self.redis.fail:
            raise RedisConnectionError("redis is down")
        results = []
        for command in self.commands:
            if command[0] == "incr":
                key = command[1]
                self.redis.counters[key] = self.redis.counters.get(key, 0) + 1
                results.append(self.redis.counters[key])
            else:
                _, key, seconds, nx = command
                if nx and key in self.redis.ttls:
                    results.append(False)
                    continue
                self.redis.ttls[key] = seconds
                results.append(True)
        self.redis.executed.append(tuple(self.commands))
        return results


class FakeRedis:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.executed: list[tuple] = []
        self.fail = False

    def pipeline(self, transaction: bool = True) -> FakePipeline:
        return FakePipeline(self)

    def delete(self, *keys: str) -> int:
        if self.fail:
            raise RedisConnectionError("redis is down")
        removed = 0
        for key in keys:
            removed += self.counters.pop(key, None) is not None
            self.ttls.pop(key, None)
        return removed


@pytest.fixture
def redis(monkeypatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(rate_limit, "redis_client", lambda: fake)
    monkeypatch.setattr(
        rate_limit.get_settings(), "mcp_login_rate_limit_per_minute", LIMIT, raising=False
    )
    return fake


def test_login_attempts_are_refused_once_the_per_ip_limit_is_passed(redis):
    for _ in range(LIMIT):
        enforce_login_rate_limit("203.0.113.9", "client-a")
    with pytest.raises(RateLimitExceeded):
        enforce_login_rate_limit("203.0.113.9", "client-a")


def test_the_counter_always_gets_a_ttl_so_a_bucket_cannot_stick_forever(redis):
    """INCR and EXPIRE must travel together; a bucket without a TTL would lock the operator out for good."""
    enforce_login_rate_limit("203.0.113.9", "client-a")
    assert redis.ttls["mcp-login:203.0.113.9"] == 60
    for commands in redis.executed:
        assert [command[0] for command in commands] == ["incr", "expire"]
        assert commands[1][3] is True  # EXPIRE ... NX, so replaying it keeps the original window


def test_a_successful_login_clears_every_bucket_it_spent(redis):
    for _ in range(LIMIT):
        enforce_login_rate_limit("203.0.113.9", "client-a")
    clear_login_rate_limit("203.0.113.9", "client-a")
    assert redis.counters == {}

    # The budget is genuinely back, not merely reported as cleared.
    for _ in range(LIMIT):
        enforce_login_rate_limit("203.0.113.9", "client-a")


def test_one_hot_address_cannot_spend_the_shared_ceilings(redis):
    """The per-IP bucket is checked first, so a single attacker stops before the global budget is gone."""
    with pytest.raises(RateLimitExceeded):
        for _ in range(LIMIT * 4):
            enforce_login_rate_limit("203.0.113.9", "attacker-client")

    # A resolved address never touches the server-wide ceiling, so it cannot be spent against others.
    assert "mcp-login:all" not in redis.counters
    # An operator arriving from another address still has their full budget.
    enforce_login_rate_limit("198.51.100.4", "operator-client")


def test_an_unresolved_address_falls_back_to_the_client_and_global_ceilings(redis):
    """Behind a misconfigured proxy every request shares one key, so the per-IP bucket is skipped."""
    for _ in range(LIMIT * CLIENT_LOGIN_LIMIT_MULTIPLIER):
        enforce_login_rate_limit(UNRESOLVED_CLIENT_IP, "client-a")
    assert f"mcp-login:{UNRESOLVED_CLIENT_IP}" not in redis.counters

    with pytest.raises(RateLimitExceeded):
        enforce_login_rate_limit(UNRESOLVED_CLIENT_IP, "client-a")
    # A different client_id is untouched, so one attacker cannot lock the operator out this way.
    enforce_login_rate_limit(UNRESOLVED_CLIENT_IP, "client-b")


def test_rotating_addresses_cannot_lock_the_operator_out(redis):
    """A server-wide counter shared by resolved addresses would be a lockout switch, so there is none.

    Rotating the source address is cheap — trivially so on IPv6 — and a global bucket that every
    request increments would let an attacker spend it and have the operator's own next attempt
    refused along with theirs. Distributed guessing is bounded by the password instead, which
    config.py refuses to let default. Each address still stops at its own per-IP budget.
    """
    for attempt in range(LIMIT * GLOBAL_LOGIN_LIMIT_MULTIPLIER + 1):
        enforce_login_rate_limit(f"203.0.113.{attempt % 200}", f"client-{attempt}")
    assert "mcp-login:all" not in redis.counters

    # The operator, arriving from an address of their own, is unaffected throughout.
    for _ in range(LIMIT):
        enforce_login_rate_limit("198.51.100.4", "operator-client")


def test_a_redis_outage_fails_closed(redis):
    redis.fail = True
    with pytest.raises(RateLimitUnavailable):
        enforce_login_rate_limit("203.0.113.9", "client-a")
    with pytest.raises(RateLimitUnavailable):
        enforce_registration_rate_limit("203.0.113.9")


def test_clearing_the_limit_during_an_outage_is_not_an_error(redis):
    """A successful login must not 500 just because the limiter cannot be reset."""
    redis.fail = True
    clear_login_rate_limit("203.0.113.9", "client-a")


def test_registration_uses_its_own_hourly_window(redis):
    limit = rate_limit.get_settings().mcp_registration_rate_limit_per_hour
    for _ in range(limit):
        enforce_registration_rate_limit("203.0.113.9")
    assert redis.ttls["mcp-register:203.0.113.9"] == 3600
    with pytest.raises(RateLimitExceeded):
        enforce_registration_rate_limit("203.0.113.9")


REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"
LOGIN_FORM = {
    "password": "a-wrong-password",
    "client_id": "any-registered-client",
    "code_challenge": "c" * 43,
    "response_type": "code",
    "redirect_uri": REDIRECT_URI,
}


class _StubSession:
    """Resolves any client_id to one registered public client, so the request reaches the limiter."""

    def get(self, _model, client_id):
        return OAuthClient(
            client_id=client_id,
            client_secret_hash=None,
            client_name="テストクライアント",
            redirect_uris=[REDIRECT_URI],
            grant_types=["authorization_code"],
            token_endpoint_auth_method="none",
        )


@pytest.fixture
def login_client() -> TestClient:
    """Only the OAuth router: app.main starts the MCP session manager, which refuses a second run."""
    app = FastAPI()
    app.include_router(oauth_api.router)
    app.dependency_overrides[get_db] = lambda: _StubSession()
    return TestClient(app)


def test_the_login_page_reports_429_once_the_limit_is_spent(redis, login_client):
    for _ in range(LIMIT):
        assert login_client.post("/oauth/authorize", data=LOGIN_FORM).status_code == 401

    exceeded = login_client.post("/oauth/authorize", data=LOGIN_FORM)
    assert exceeded.status_code == 429
    assert "試行回数" in exceeded.text


def test_the_login_page_refuses_with_503_while_redis_is_unreachable(redis, login_client):
    """Fail closed: without a working limiter the password form must not accept guesses at all."""
    redis.fail = True
    response = login_client.post("/oauth/authorize", data=LOGIN_FORM)
    assert response.status_code == 503
    assert "運営者パスワード" not in response.text


def test_registration_from_an_unresolved_address_cannot_block_every_new_client(redis):
    """An unattributable registration shares one bucket, so that bucket must not be the precise limit.

    Keyed on a bare "unknown" at the per-address limit, twenty throwaway registrations would block
    every legitimate new MCP client for the rest of the hour — the same lockout switch the login
    buckets were reshaped to avoid.
    """
    for _ in range(REGISTRATION_LIMIT):
        enforce_registration_rate_limit(UNRESOLVED_CLIENT_IP)
    assert f"mcp-register:{UNRESOLVED_CLIENT_IP}" not in redis.counters
    # Still well inside the shared ceiling, so a real client can still register.
    enforce_registration_rate_limit(UNRESOLVED_CLIENT_IP)

    with pytest.raises(RateLimitExceeded):
        for _ in range(REGISTRATION_LIMIT * GLOBAL_LOGIN_LIMIT_MULTIPLIER):
            enforce_registration_rate_limit(UNRESOLVED_CLIENT_IP)


def test_registration_from_a_resolved_address_is_counted_precisely(redis):
    for _ in range(REGISTRATION_LIMIT):
        enforce_registration_rate_limit("203.0.113.9")
    with pytest.raises(RateLimitExceeded):
        enforce_registration_rate_limit("203.0.113.9")
    # Another address keeps its own budget.
    enforce_registration_rate_limit("198.51.100.4")
