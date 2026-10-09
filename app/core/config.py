from functools import lru_cache
from ipaddress import IPv4Network, IPv6Network, ip_network
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
    log_level: str = "INFO"

    database_url: str
    test_database_url: str | None = None

    postgres_db: str = "green_garden"
    postgres_user: str = "green_garden"
    postgres_password: str = "green_garden"
    postgres_port: int = 5432

    # SQLAlchemy connection pool (per uvicorn worker)
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: float = 30.0

    # Prometheus scrape token; /metrics returns 404 while unset.
    metrics_token: str | None = None

    # Rate limiting (SlowAPI). `memory://` counters are per worker; use Redis
    # whenever more than one worker or container serves traffic.
    rate_limit_enabled: bool = True
    rate_limit_storage_uri: str = "memory://"
    rate_limit_strategy: Literal["fixed-window", "moving-window"] = "moving-window"
    # Ceiling per client IP across all non-exempt routes.
    rate_limit_default: str = "200/minute"
    rate_limit_login: str = "5/minute;20/hour"
    rate_limit_login_email_failures: str = "10/hour"
    rate_limit_refresh: str = "30/minute"
    rate_limit_chat: str = "10/minute;60/hour;200/day"
    # Shared by every client: caps DeepSeek spend.
    rate_limit_chat_global: str = "1000/hour"
    rate_limit_public_write: str = "10/minute;50/hour"
    rate_limit_quote: str = "30/minute"
    # Peers allowed to set X-Forwarded-For: comma-separated IPs or CIDRs.
    trusted_proxies: str = "127.0.0.1,::1"

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

    # Next.js storefront cache webhook; disabled unless both are set.
    storefront_revalidate_url: str | None = None
    storefront_revalidate_secret: str | None = None

    # SePay bank transfer: a fixed VA (or account) plus a per-order payment code.
    # Bank transfer is offered only when the account number and webhook key are set.
    sepay_webhook_api_key: str | None = None
    sepay_bank_code: str = "MB"
    sepay_bank_name: str | None = None
    sepay_account_number: str | None = None
    sepay_account_holder: str | None = None

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
        "metrics_token",
        "weaviate_api_key",
        "openai_api_key",
        "deepseek_api_key",
        "storefront_revalidate_url",
        "storefront_revalidate_secret",
        "sepay_webhook_api_key",
        "sepay_bank_name",
        "sepay_account_number",
        "sepay_account_holder",
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

    def bank_transfer_enabled(self) -> bool:
        return bool(self.sepay_account_number and self.sepay_webhook_api_key)

    def trusted_proxy_networks(self) -> list[IPv4Network | IPv6Network]:
        return [
            ip_network(entry.strip(), strict=False)
            for entry in self.trusted_proxies.split(",")
            if entry.strip()
        ]

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
