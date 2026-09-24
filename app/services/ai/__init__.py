"""AI services (knowledge indexing + DeepSeek chat)."""

from app.services.ai.deepseek import DeepSeekService, get_deepseek_service

__all__ = [
    "DeepSeekService",
    "get_deepseek_service",
]