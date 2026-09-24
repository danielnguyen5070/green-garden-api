from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Green Garden API"
    app_env: str = "development"
    debug: bool = False

    database_url: str
    test_database_url: str | None = None

    postgres_db: str = "green_garden"
    postgres_user: str = "green_garden"
    postgres_password: str = "green_garden"
    postgres_port: int = 5432

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Auth cookies
    auth_cookie_secure: bool = False
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    auth_access_cookie_name: str = "gg_access_token"
    auth_refresh_cookie_name: str = "gg_refresh_token"
    auth_cookie_path: str = "/"
    auth_cookie_domain: str | None = None

    # CORS — comma-separated Next.js origins (parsed to a list)
    cors_origins: str = "http://localhost:3000"

    # Weaviate (simple URL style)
    weaviate_enabled: bool = False
    weaviate_url: str = "http://localhost:8080"
    weaviate_grpc_port: int = 50051
    weaviate_api_key: str | None = None
    rag_top_k: int = 3
    openai_api_key: str | None = None

    # DeepSeek
    deepseek_api_key: str | None = None
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_timeout_seconds: float = 60.0

    @field_validator("auth_cookie_domain", mode="before")
    @classmethod
    def _normalize_auth_cookie_domain(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value  # type: ignore[return-value]

    @field_validator(
        "weaviate_api_key",
        "openai_api_key",
        "deepseek_api_key",
        mode="before",
    )
    @classmethod
    def _normalize_optional_str(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value  # type: ignore[return-value]

    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def weaviate_http_parts(self) -> tuple[str, int, bool]:
        """Parse ``WEAVIATE_URL`` into ``(host, port, secure)``."""
        raw = (self.weaviate_url or "").strip()
        parsed = urlparse(raw if "://" in raw else f"http://{raw}")
        host = parsed.hostname or "localhost"
        secure = parsed.scheme == "https"
        port = parsed.port or (443 if secure else 80)
        return host, port, secure


@lru_cache
def get_settings() -> Settings:
    return Settings()
