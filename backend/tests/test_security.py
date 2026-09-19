import pytest
from pydantic import ValidationError

from app.config import Settings
from app.security import valid_internal_token, valid_mcp_authorization, valid_operator_password


def test_internal_api_token_requires_an_exact_match():
    expected = "a-secure-internal-token"
    assert valid_internal_token(expected, expected)
    assert not valid_internal_token(None, expected)
    assert not valid_internal_token("wrong-token-value", expected)


def test_mcp_token_requires_bearer_scheme_and_exact_match():
    expected = "a-secure-operator-token"
    assert valid_mcp_authorization(f"Bearer {expected}", expected)
    assert valid_mcp_authorization(f"bearer {expected}", expected)
    assert not valid_mcp_authorization(expected, expected)
    assert not valid_mcp_authorization("Basic a-secure-operator-token", expected)


def test_non_ascii_credentials_compare_instead_of_raising():
    """`hmac.compare_digest` refuses str arguments holding non-ASCII, which used to be a 500 per attempt.

    Both directions matter: a Japanese operator password must still work, and an attacker posting one
    against an ASCII password must get a plain rejection rather than an unhandled error.
    """
    password = "とても長い運営者パスワード"
    assert valid_operator_password(password, password)
    assert not valid_operator_password(password, "an-ascii-operator-password")
    assert not valid_operator_password("an-ascii-operator-password", password)

    token = "内部トークン-0123456789abcdef"
    assert valid_internal_token(token, token)
    assert not valid_internal_token("wrong-token-value", token)
    assert valid_mcp_authorization(f"Bearer {token}", token)
    assert not valid_mcp_authorization("Bearer 別のトークン", token)


def test_production_rejects_local_development_tokens():
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            api_internal_token="local-development-internal-token",
            mcp_api_token="local-development-mcp-token",
        )


def test_production_rejects_the_published_operator_password():
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            api_internal_token="production-internal-token-0001",
            mcp_api_token="production-operator-token-0001",
            mcp_oauth_enabled=True,
            mcp_public_url="https://relua.example",
            mcp_operator_password="local-development-operator-password",
        )


def test_an_unknown_environment_value_refuses_to_start():
    """The old check was `environment.lower() == "production"`, so every typo silently meant development."""
    for value in ("prod", "Production", "staging", ""):
        with pytest.raises(ValidationError):
            Settings(
                environment=value,
                api_internal_token="local-development-internal-token",
                mcp_api_token="local-development-mcp-token",
            )


def test_development_is_the_only_way_to_keep_the_published_secrets():
    settings = Settings(
        environment="development",
        api_internal_token="local-development-internal-token",
        mcp_api_token="local-development-mcp-token",
    )
    assert settings.environment == "development"


def test_production_accepts_unique_tokens():
    settings = Settings(
        environment="production",
        api_internal_token="production-internal-token-0001",
        mcp_api_token="production-operator-token-0001",
    )
    assert settings.environment == "production"
