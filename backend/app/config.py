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

    @model_validator(mode="after")
    def reject_development_tokens_in_production(self) -> "Settings":
        if self.environment.lower() == "production":
            tokens = (self.api_internal_token, self.mcp_api_token)
            if any(token.startswith("local-development-") for token in tokens):
                raise ValueError("production requires unique API_INTERNAL_TOKEN and MCP_API_TOKEN values")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
