"""Rupee amounts in crore, the unit Indian investors read. Code converts; models only copy."""

from __future__ import annotations

import re

UNIT_TO_CRORE = {
    "thousand": 1e-4,
    "lakh": 0.01,
    "million": 0.1,
    "crore": 1.0,
    "billion": 100.0,
    "rupee": 1e-7,  # last: "million rupees" is millions
}


def crore_factor(unit: str | None) -> float | None:
    """'crore', 'Crores', 'million INR', 'INR billion' -> the factor that turns it into crore."""
    if not unit:
        return None
    u = unit.lower()
    for word, factor in UNIT_TO_CRORE.items():
        if re.search(rf"\b{word}s?\b", u):
            return factor
    return None


def to_crore(value: float | None, unit: str | None) -> float | None:
    if value is None:
        return None
    factor = crore_factor(unit)
    if not factor:
        return None
    crore = round(value * factor, 2)
    # Under ₹1 lakh is a per-share figure ("dividend of ₹5"), not a size worth showing.
    return crore if crore >= 0.01 else None
