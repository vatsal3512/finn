"""Indian financial-year periods. FY27 runs from April 2026 to March 2027.

Periods are compared by their last month, "YYYY-MM", which is how screener.in labels its
columns: Q1 FY27 ends 2026-06 and FY27 ends 2027-03.
"""

from __future__ import annotations

import re

_FY = r"FY\s*'?(?:20)?(\d{2})(?:\s*[-/]\s*(?:20)?(\d{2}))?"  # FY27, FY2027, FY2026-27
_PATTERNS = (
    (re.compile(rf"^Q([1-4])\s*{_FY}$", re.I), "quarter"),
    (re.compile(rf"^H([12])\s*{_FY}$", re.I), "half"),
    (re.compile(rf"^9M\s*{_FY}$", re.I), "nine_months"),
    (re.compile(rf"^{_FY}$", re.I), "year"),
)
_QUARTER_END = {1: "06", 2: "09", 3: "12"}


def parse(label: str | None) -> tuple[str, str] | None:
    """("YYYY-MM" of the period's last month, granularity), or None if not a period."""
    if not label:
        return None
    s = " ".join(label.split())
    for rx, kind in _PATTERNS:
        m = rx.match(s)
        if not m:
            continue
        g = m.groups()
        fy = 2000 + int(g[-1] or g[-2])  # in "FY2026-27" the second year names it
        if kind == "year":
            return f"{fy}-03", kind
        if kind == "nine_months":
            return f"{fy - 1}-12", kind
        n = int(g[0])
        if kind == "half":
            return (f"{fy - 1}-09" if n == 1 else f"{fy}-03"), kind
        return (f"{fy}-03" if n == 4 else f"{fy - 1}-{_QUARTER_END[n]}"), kind
    return None


def quarter_label(period_end: str) -> str:
    """'2026-06' -> 'Q1 FY27'."""
    year, month = int(period_end[:4]), int(period_end[5:7])
    q = {6: 1, 9: 2, 12: 3, 3: 4}[month]
    fy = year + 1 if month >= 4 else year
    return f"Q{q} FY{fy % 100:02d}"


def year_label(period_end: str) -> str:
    """'2026-03' -> 'FY26'."""
    return f"FY{int(period_end[:4]) % 100:02d}"
