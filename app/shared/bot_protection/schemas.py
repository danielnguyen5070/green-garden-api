"""Bot-signal fields shared by the public storefront forms.

They are read by `app.shared.bot_protection.service` in the route and never
reach the order or review business logic.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["BotSignals"]


class BotSignals(BaseModel):
    """
    Honeypot and fill-time signals sent by every public form.

    `website` is a hidden field a human never fills in. `form_elapsed_ms` is
    how long the form was open before it was submitted.
    """

    website: str | None = Field(default=None, max_length=255)
    form_elapsed_ms: int | None = None
