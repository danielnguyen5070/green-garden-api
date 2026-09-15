from functools import lru_cache

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

    postgres_db: str = "green_garden"
    postgres_user: str = "green_garden"
    postgres_password: str = "green_garden"
    postgres_port: int = 5432


@lru_cache
def get_settings() -> Settings:
    return Settings()
