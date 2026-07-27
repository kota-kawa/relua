import hmac


def valid_internal_token(received: str | None, expected: str) -> bool:
    return bool(received) and hmac.compare_digest(received, expected)


def valid_mcp_authorization(authorization: str | None, expected: str) -> bool:
    if not authorization:
        return False
    scheme, separator, token = authorization.partition(" ")
    return separator == " " and scheme.lower() == "bearer" and hmac.compare_digest(token, expected)
