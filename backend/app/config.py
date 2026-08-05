from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    app_name: str = "All Job API"
    environment: str = "development"
    database_url: str = "sqlite:///./alljob.db"
    redis_url: str = "redis://localhost:6379/0"
    api_internal_token: str = Field(default="local-development-internal-token", min_length=16)
    mcp_api_token: str = Field(default="local-development-mcp-token", min_length=16)
    mcp_rate_limit_per_minute: int = Field(default=30, ge=1, le=300)

    #: OAuth lets remote clients (ChatGPT, Claude) connect by sending the operator to a relua login page.
    #: Off by default so an existing loopback-only deployment keeps its single static-token setup.
    mcp_oauth_enabled: bool = False
    #: Public origin the MCP endpoint is reachable at. Becomes the OAuth issuer and the resource identifier.
    mcp_public_url: str = "http://localhost:8000"
    mcp_operator_password: str = Field(default="local-development-operator-password", min_length=12)
    mcp_access_token_ttl_seconds: int = Field(default=3600, ge=300, le=86400)
    #: 0 keeps refresh tokens valid indefinitely, so a connected client stays connected without re-login.
    mcp_refresh_token_ttl_days: int = Field(default=0, ge=0, le=3650)
    mcp_authorization_code_ttl_seconds: int = Field(default=120, ge=30, le=600)
    mcp_login_rate_limit_per_minute: int = Field(default=5, ge=1, le=60)
    mcp_registration_rate_limit_per_hour: int = Field(default=20, ge=1, le=1000)

    @property
    def issuer(self) -> str:
        return self.mcp_public_url.rstrip("/")

    @property
    def resource_identifier(self) -> str:
        return f"{self.issuer}/mcp"

    @model_validator(mode="after")
    def reject_development_secrets_in_production(self) -> "Settings":
        if self.environment.lower() == "production":
            secrets_in_use = (self.api_internal_token, self.mcp_api_token)
            if any(secret.startswith("local-development-") for secret in secrets_in_use):
                raise ValueError("production requires unique API_INTERNAL_TOKEN and MCP_API_TOKEN values")
            if self.mcp_oauth_enabled:
                if self.mcp_operator_password.startswith("local-development-"):
                    raise ValueError("production requires a unique MCP_OPERATOR_PASSWORD value")
                if not self.mcp_public_url.startswith("https://"):
                    raise ValueError("production requires an https MCP_PUBLIC_URL")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
