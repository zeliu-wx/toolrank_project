"""Canonical internal DASP category identifiers."""

from __future__ import annotations

import re


DASP10_CATEGORIES = [
    "reentrancy",
    "access_control",
    "arithmetic",
    "unchecked_low_level_calls",
    "denial_of_service",
    "bad_randomness",
    "front_running",
    "time_manipulation",
    "short_addresses",
    "unknown_unknowns",
]


_CATEGORY_ALIASES = {
    "denial_service": "denial_of_service",
    "denial_of_service": "denial_of_service",
    "unchecked_low_calls": "unchecked_low_level_calls",
    "unchecked_ll_calls": "unchecked_low_level_calls",
    "unchecked_low_level_calls": "unchecked_low_level_calls",
    "other": "unknown_unknowns",
    "unknown": "unknown_unknowns",
    "unknown_unknowns": "unknown_unknowns",
}


def normalize_category(value: object) -> str:
    """Return one lowercase underscore-separated internal category label."""
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return _CATEGORY_ALIASES.get(normalized, normalized)
