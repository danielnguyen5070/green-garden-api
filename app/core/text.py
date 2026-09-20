"""Text normalization helpers for user-provided identifiers."""

from __future__ import annotations

import re

_SLUG_SEPARATORS = re.compile(r"[\s_]+")
_SLUG_INVALID = re.compile(r"[^a-z0-9-]")
_SLUG_DASHES = re.compile(r"-{2,}")
_PHONE_WHITESPACE = re.compile(r"\s+")
_PHONE_SEPARATORS = re.compile(r"[\s().-]+")
# LIKE / ILIKE treat `\`, `%` and `_` as metacharacters when an escape char is set.
_ILIKE_META = re.compile(r"([\\%_])")

_VN_COUNTRY_CODE = "84"
# A Vietnamese subscriber number is 9 digits behind the trunk `0` / the `84`
# country code, so `84` + 9 digits is the only bare form we dare to rewrite.
_VN_NATIONAL_DIGITS = 9


def normalize_search_query(query: str) -> str:
    """Trim user search input. Whitespace-only becomes an empty string."""
    return query.strip()


def escape_ilike_pattern(value: str) -> str:
    """
    Escape `\\`, `%` and `_` so a user keyword is matched literally under ILIKE.

    Pair with `Column.ilike(pattern, escape="\\\\")` (a single backslash escape).
    """
    return _ILIKE_META.sub(r"\\\1", value)


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


def normalize_vn_phone(phone: str) -> str:
    """
    Rewrite a Vietnamese number to the canonical local form starting with `0`.

    `+84901234567`, `84 901 234 567` and `090-123-4567` all become
    `0901234567`, so the same shopper is one customer whichever way the
    checkout form was filled in. Numbers that are not recognisably Vietnamese
    are only stripped of their separators and otherwise left as typed.
    """
    value = _PHONE_SEPARATORS.sub("", phone.strip())
    bare_length = len(_VN_COUNTRY_CODE) + _VN_NATIONAL_DIGITS

    national: str | None = None
    if value.startswith(f"+{_VN_COUNTRY_CODE}"):
        national = value.removeprefix(f"+{_VN_COUNTRY_CODE}")
    elif value.startswith(_VN_COUNTRY_CODE) and len(value) == bare_length:
        national = value.removeprefix(_VN_COUNTRY_CODE)

    if national is None:
        return value
    # `+840901234567` is written by hand often enough to be worth handling.
    subscriber = national.lstrip("0")
    return f"0{subscriber}" if subscriber else value
