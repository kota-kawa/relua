import pytest
from pydantic import ValidationError

from app.config import Settings
from app.security import valid_internal_token, valid_mcp_authorization


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


def test_production_rejects_local_development_tokens():
    with pytest.raises(ValidationError):
        Settings(environment="production")


def test_production_accepts_unique_tokens():
    settings = Settings(
        environment="production",
        api_internal_token="production-internal-token-0001",
        mcp_api_token="production-operator-token-0001",
    )
    assert settings.environment == "production"
