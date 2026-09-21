"""Small, explicit company-level aliases used only by analytics rollups."""

from __future__ import annotations

from typing import Optional


ALPHABET_SYMBOLS = {"GOOG", "GOOGL"}
ALPHABET_KEY = "alphabet-goog-googl"
ALPHABET_LABEL = "Alphabet (GOOG/GOOGL)"


def company_identity(symbol: Optional[str], fallback_label: str) -> tuple[str, str]:
    """Return a stable analytical company key and display label.

    This intentionally leaves securities, prices, and raw provider holdings
    untouched; it only merges Alphabet's two listed share classes in rollups.
    """
    normalized = (symbol or "").strip().upper()
    if normalized in ALPHABET_SYMBOLS:
        return ALPHABET_KEY, ALPHABET_LABEL
    return normalized or fallback_label.strip().upper(), fallback_label
