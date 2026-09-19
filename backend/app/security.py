import hashlib
import hmac
import secrets


def _constant_time_equals(received: str, expected: str) -> bool:
    """Compare two credentials without leaking their length through timing.

    ``hmac.compare_digest`` raises TypeError for ``str`` arguments holding any character above U+007F,
    so a Japanese MCP_OPERATOR_PASSWORD — or merely an attacker posting one — turned every comparison
    into an unhandled 500. Encoding both sides to UTF-8 first keeps the comparison on the bytes path,
    which accepts any input and stays constant time for equal-length values.
    """
    return hmac.compare_digest(received.encode("utf-8"), expected.encode("utf-8"))


def valid_internal_token(received: str | None, expected: str) -> bool:
    return bool(received) and _constant_time_equals(received, expected)


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token:
        return None
    return token


def valid_mcp_authorization(authorization: str | None, expected: str) -> bool:
    token = bearer_token(authorization)
    return token is not None and _constant_time_equals(token, expected)


def valid_operator_password(received: str | None, expected: str) -> bool:
    return bool(received) and _constant_time_equals(received, expected)


def token_hash(token: str) -> str:
    """Hash a bearer or refresh token for storage, so a database leak does not hand over live credentials."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_secret(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"
