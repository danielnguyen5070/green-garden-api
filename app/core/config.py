from functools import lru_cache
from typing import Literal

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

    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
