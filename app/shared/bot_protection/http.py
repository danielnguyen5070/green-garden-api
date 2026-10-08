"""Route-level bot check shared by the public review and checkout forms."""

from __future__ import annotations

from fastapi import HTTPException, status

from app.shared.bot_protection.schemas import BotSignals
from app.shared.bot_protection.service import (
    BotSignalRejectedError,
    verify_bot_signals,
)

BOT_REJECTED_RESPONSES = {
    status.HTTP_403_FORBIDDEN: {
        "description": "Honeypot filled or form submitted too quickly"
    }
}


def verify_bot_signals_or_403(payload: BotSignals) -> None:
    try:
        verify_bot_signals(payload)
    except BotSignalRejectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Submission rejected",
        ) from exc
