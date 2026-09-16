"""Text normalization helpers for user-provided identifiers."""

from __future__ import annotations

import re

_SLUG_SEPARATORS = re.compile(r"[\s_]+")
_SLUG_INVALID = re.compile(r"[^a-z0-9-]")
_SLUG_DASHES = re.compile(r"-{2,}")
_PHONE_WHITESPACE = re.compile(r"\s+")


def normalize_slug(slug: str) -> str:
    """Lowercase, trim and collapse a slug to `a-z0-9-` characters."""
    value = _SLUG_SEPARATORS.sub("-", slug.strip().lower())
    value = _SLUG_INVALID.sub("", value)
    return _SLUG_DASHES.sub("-", value).strip("-")


def normalize_sku(sku: str) -> str:
    """Trim and uppercase a SKU for consistent uniqueness checks."""
    return sku.strip().upper()


def normalize_phone(phone: str) -> str:
    """
    Drop every space so `090 123 4567` and `0901234567` are the same customer.

    Separators such as `+`, `-` and `()` are kept as typed.
    """
    return _PHONE_WHITESPACE.sub("", phone.strip())
