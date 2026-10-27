"""The rule pass decides what never reaches the AI, so its mistakes are silent. Pin them."""

import pytest

from finn.rules import CATEGORIES, DEFAULT_TIER, RULES, TIERS, classify


@pytest.mark.parametrize(
    ("label", "headline", "category", "tier", "needs_ai"),
    [
        # routine paperwork: settled, never read
        ("Trading Window", "closure of trading window", "unclassified", "routine", False),
        (
            "Copy of Newspaper Publication",
            "results advertisement",
            "unclassified",
            "routine",
            False,
        ),
        ("ESOP/ESOS/ESPS", "allotment of 9138522 shares", "unclassified", "routine", False),
        (
            "Certificate under SEBI (Depositories and Participants) Regulations, 2018",
            "",
            "unclassified",
            "routine",
            False,
        ),
        ("Monitoring Agency Report", "", "unclassified", "routine", False),
        # trading window must not be mistaken for insider trading
        ("Trading Window", "insider trading code", "unclassified", "routine", False),
        # calls and meetings, worded the NSE way and the BSE way
        (
            "Analysts/Institutional Investor Meet/Con. Call Updates",
            "Transcript",
            "earnings_call",
            "routine",
            False,
        ),
        (
            "Announcement under Regulation 30 (LODR)-Analyst / Investor Meet - Outcome",
            "Transcript of Earnings Call",
            "earnings_call",
            "routine",
            False,
        ),
        ("Shareholders meeting", "Notice of Postal Ballot", "postal_ballot", "routine", False),
        # material events: category known, AI still summarises
        (
            "Outcome of Board Meeting",
            "submitted the financial results for the period ended September 30, 2026",
            "results",
            "must_see",
            True,
        ),
        (
            "Change in Management",
            "change in Managing Director and CEO",
            "management_change",
            "must_see",
            True,
        ),
        (
            "Appointment",
            "Appointment of Ms Rashmi Joshi as Independent Director",
            "management_change",
            "glance",
            True,
        ),
        ("Corporate Insolvency Resolution Process", "", "litigation", "must_see", True),
        ("Rights Issue", "2 shares for every 25 held", "fund_raise", "must_see", True),
        (
            "Updates",
            "Submission of Letter of Offer for Rights Issue of partly paid-up equity shares",
            "fund_raise",
            "must_see",
            True,
        ),
        (
            "Updates",
            "Company announcement on pledge of shares by Promoter",
            "pledging",
            "must_see",
            True,
        ),
        (
            "Allotment of Securities",
            "allotment of 2,12,000 Non Convertible Debentures",
            "fund_raise",
            "routine",
            False,
        ),
        ("Acquisition", "Incorporation of Wholly Owned Subsidiary", "M&A", "glance", True),
        ("Amalgamation/Merger", "NCLT order sanctioning the scheme", "M&A", "must_see", True),
        ("Credit Rating", "", "credit_rating", "glance", True),
        ("General Updates", "SIAM Report - July - September 2026", "press_release", "glance", True),
    ],
)
def test_known_filings(label, headline, category, tier, needs_ai):
    v = classify(label, headline)
    assert (v.category, v.tier, v.needs_ai) == (category, tier, needs_ai), v.rule


@pytest.mark.parametrize(
    ("label", "headline"),
    [
        ("General Updates", "informed the Exchange about General Updates"),
        ("Press Release", "a press release dated October 21, 2026"),
    ],
)
def test_vague_labels_go_to_ai(label, headline):
    v = classify(label, headline)
    assert v.category is None and v.needs_ai


def test_rule_table_is_consistent():
    names = [r.name for r in RULES]
    assert len(names) == len(set(names)), "rule names must be unique for auditability"
    for r in RULES:
        assert r.category is None or r.category in CATEGORIES
        assert r.tier is None or r.tier in TIERS
    assert set(DEFAULT_TIER) == set(CATEGORIES)
