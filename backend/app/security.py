import hashlib
import hmac
import secrets


def valid_internal_token(received: str | None, expected: str) -> bool:
    return bool(received) and hmac.compare_digest(received, expected)


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token:
        return None
    return token


def valid_mcp_authorization(authorization: str | None, expected: str) -> bool:
    token = bearer_token(authorization)
    return token is not None and hmac.compare_digest(token, expected)


def valid_operator_password(received: str | None, expected: str) -> bool:
    return bool(received) and hmac.compare_digest(received, expected)


def token_hash(token: str) -> str:
    """Hash a bearer or refresh token for storage, so a database leak does not hand over live credentials."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_secret(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"
