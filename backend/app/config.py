from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Secrets shipped in `.env.example` and in this repository carry this prefix. Anyone who can read the
#: repository knows them, so they are treated as "no secret at all" rather than as a weak one.
DEVELOPMENT_SECRET_PREFIX = "local-development-"
HISTORY_RETENTION_DAYS = 90


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    app_name: str = "All Job API"
    #: A Literal, not a free string: the old `environment.lower() == "production"` check treated every
    #: typo ("prod", "Production", an unset variable) as development and silently disabled the secret
    #: guard below. An unknown value must refuse to boot instead of quietly downgrading the checks.
    environment: Literal["development", "production"] = "development"
    database_url: str = "sqlite:///./alljob.db"
    redis_url: str = "redis://localhost:6379/0"
    api_internal_token: str = Field(default="local-development-internal-token", min_length=16)
    mcp_api_token: str = Field(default="local-development-mcp-token", min_length=16)
    #: Public origin of the Next.js site. Every record MCP returns carries its detail page URL,
    #: so a remote client can cite the entry instead of only naming it.
    site_url: str = "http://localhost:3100"
    history_archive_dir: str = "/var/lib/relua/history-archive"

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

    @property
    def site_origin(self) -> str:
        return self.site_url.rstrip("/")

    @model_validator(mode="after")
    def reject_published_development_secrets(self) -> "Settings":
        """Refuse to start while a secret that is published in this repository is actually in use.

        `/mcp` and the OAuth login are reachable from the public internet through `relua.conf`, so a
        `local-development-` token is an open door, not a placeholder. The only escape hatch is an
        explicit `ENVIRONMENT=development`: the check is written as "development opts in" rather than
        "production opts out" so that a missing or misspelled ENVIRONMENT fails closed. docker-compose
        pairs this with `${VAR:?}` forms, so an unset secret stops the stack before this is reached.
        """
        if self.environment == "development":
            return self

        secrets_in_use = {
            "API_INTERNAL_TOKEN": self.api_internal_token,
            "MCP_API_TOKEN": self.mcp_api_token,
        }
        if self.mcp_oauth_enabled:
            secrets_in_use["MCP_OPERATOR_PASSWORD"] = self.mcp_operator_password
        published = sorted(
            name for name, secret in secrets_in_use.items() if secret.startswith(DEVELOPMENT_SECRET_PREFIX)
        )
        if published:
            raise ValueError(f"{self.environment} requires unique values for: {', '.join(published)}")
        if self.mcp_oauth_enabled and not self.mcp_public_url.startswith("https://"):
            raise ValueError(f"{self.environment} requires an https MCP_PUBLIC_URL")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
