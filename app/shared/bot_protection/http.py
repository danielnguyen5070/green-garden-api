"""OpenAPI response docs shared by the public review and checkout forms."""

from __future__ import annotations

from fastapi import status

BOT_REJECTED_RESPONSES = {
    status.HTTP_403_FORBIDDEN: {
        "description": "Honeypot filled or form submitted too quickly"
    }
}
