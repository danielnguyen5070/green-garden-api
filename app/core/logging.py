"""Application logging configuration.

Never log passwords, JWTs, cookies or raw request bodies.
"""

from __future__ import annotations

import logging
from logging.config import dictConfig

from app.core.config import Settings
from app.core.request_context import get_request_id


class RequestIdFilter(logging.Filter):
    """Attach the current request id (or `-`) to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


def configure_logging(settings: Settings) -> None:
    level = "DEBUG" if settings.debug else settings.log_level.upper()
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"request_id": {"()": RequestIdFilter}},
            "formatters": {
                "default": {
                    "format": (
                        "%(asctime)s %(levelname)s [%(name)s] "
                        "[request_id=%(request_id)s] %(message)s"
                    ),
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["request_id"],
                },
            },
            "loggers": {
                "app": {"level": level},
            },
            "root": {"level": "WARNING", "handlers": ["console"]},
        }
    )
