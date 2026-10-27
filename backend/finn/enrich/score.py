"""Priority score for "Today's 3", and grouping of filings about the same event.

The score is deliberately simple and explainable: a base by tier, a bonus by category,
and a bonus when the market reacted. A results day usually produces three or four
filings (the statement, a press release, a presentation, a newspaper ad). They share a
group, so Today's 3 shows the event once, not four times.
"""

from __future__ import annotations

import re

TIER_BASE = {"must_see": 100.0, "glance": 40.0, "routine": 0.0, None: 20.0}
CATEGORY_BONUS = {
    "results": 20,
    "management_change": 6,
    "M&A": 12,
    "fund_raise": 10,
    "pledging": 12,
    "litigation": 8,
    "credit_rating": 4,
    "insider_trading": 4,
}
TOP_ROLE = re.compile(
    r"\b(ceo|cfo|managing director|\bmd\b|chief executive|chief financial|chairman)\b", re.I
)


def score(tier, category, title_text: str, sentiment: str | None, reaction) -> float:
    s = TIER_BASE.get(tier, 20.0) + CATEGORY_BONUS.get(category or "", 0)
    if category == "management_change" and TOP_ROLE.search(title_text or ""):
        s += 12  # a CEO or CFO change matters far more than an independent director
    if sentiment == "negative":
        s += 5  # for someone who owns the stock, bad news is more urgent than good
    if reaction is not None:
        if reaction.ret_pct is not None and abs(reaction.ret_pct) >= 5:
            s += 15
        if reaction.vol_ratio is not None and reaction.vol_ratio >= 2:
            s += 10
    return round(s, 1)


def group_id(symbol: str, category: str | None, filed_at: str) -> str:
    """Same company, same kind of event, same day: one group."""
    day = filed_at[:10]
    if category in ("results", "earnings_call"):
        category = "results"
    return f"{symbol}:{category or 'other'}:{day}"
