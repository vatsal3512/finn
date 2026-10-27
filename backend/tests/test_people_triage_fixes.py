"""Regression tests for the problems found in the hand review of live AI answers."""

import pytest

from finn.contracts import PersonChange
from finn.enrich.people import _excerpt, same_person
from finn.enrich.triage import to_crore


@pytest.mark.parametrize(
    ("value", "unit", "crore"),
    [
        (42646.09, "million", 4264.61),  # Persistent's QIP, which the model got 10x wrong
        (2.79, "crore", 2.79),  # Polycab's insolvency claim
        (1250, "Crores", 1250.0),
        (5, "lakh", 0.05),
        (3.2, "billion", 320.0),
        (None, "crore", None),
        (100, None, None),
        (5, "rupees", None),  # Mazagon Dock's ₹5 dividend per share is not a deal size
    ],
)
def test_code_converts_units(value, unit, crore):
    assert to_crore(value, unit) == crore


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Rohit Shanna", "Mr. Rohit Sharma"),  # Nazara's scanned letter of 13 October
        ("Mr. Anup Bagchi", "Anup  Bagchi"),
        ("Anup Bagchl", "Anup Bagchi"),
        ("Atul B. Lall", "Atul Lall"),
    ],
)
def test_same_person_despite_ocr_and_initials(a, b):
    assert same_person(a, b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Rohit Sharma", "Mohit Sharma"),  # similarity 0.92, yet different people
        ("Rakesh Shah", "Ramesh Shah"),  # similarity 0.91, yet different people
        ("Rohit Sharma", "Rakesh Shah"),
    ],
)
def test_similar_names_are_not_merged(a, b):
    assert not same_person(a, b)


def test_excerpt_reaches_a_profile_deep_in_an_annexure():
    filler = "The Board considered routine matters of the Company. " * 600  # ~32,000 chars
    letter = (
        "Outcome of Board Meeting held today.\n" + filler
        + "Annexure D. Appointment of Mr. Arun Agrawal as Chief Financial Officer. Brief profile: "
        "Chartered Accountant, earlier Global CFO at Ness Digital Engineering and Mastek."
    )  # fmt: skip
    ex = _excerpt(letter)
    assert len(ex) <= 12000 + 50
    assert "Arun Agrawal" in ex and "Ness Digital" in ex
    assert ex.startswith("Outcome of Board Meeting")


def test_reappointment_is_its_own_kind_of_change():
    c = PersonChange(person="Atul B. Lall", role="Managing Director", change="reappointment")
    assert c.change == "reappointment"


def test_split_ocr_name_matches():
    assert same_person("Roh it Shanna", "Rohit Sharma")  # Nazara, 13 October


def test_rupee_sign_restored_from_ocr_tilde():
    from finn.textclean import clean

    assert clean("Interim Dividend of ~5/- per share; facilities of ~ 1,250 Crores") == (
        "Interim Dividend of ₹5/- per share; facilities of ₹1,250 Crores"
    )


def test_company_name_stripped_from_titles():
    from finn.enrich.triage import strip_company

    assert (
        strip_company("Maruti Suzuki Q2 FY27 Financial Results", "MARUTI")
        == "Q2 FY27 Financial Results"
    )
    assert (
        strip_company("Mazagon Dock Approves Credit Facility", "MAZDOCK")
        == "Approves Credit Facility"
    )
    assert (
        strip_company("Record date set for interim dividend", "MAZDOCK")
        == "Record date set for interim dividend"
    )


def test_tier_is_part_of_the_cache_key():
    from finn.ai.llm import cache_key

    assert cache_key("t", "v", "s", "p", [], "lite") != cache_key("t", "v", "s", "p", [], "flash")


def test_important_filing_answered_by_a_stand_in_is_asked_again(tmp_path):
    from finn.enrich import triage
    from finn.store import connect, upsert

    conn = connect(tmp_path / "t.db")
    base = {"symbol": "HDFCBANK", "exchange": "NSE", "filed_at": "2099-01-01T10:00:00+05:30",
            "needs_ai": 1, "tier": "glance", "source_url": "u", "fetched_at": "x"}  # fmt: skip
    upsert(conn, "filings", [{**base, "id": "nse:1", "category": "management_change"},
                             {**base, "id": "nse:2", "category": "other"}], ("id",))  # fmt: skip
    lite = triage.GEMINI_ROUTES[triage.Tier.LITE].model
    upsert(conn, "filing_insights", [
        {"filing_id": fid, "model": lite, "prompt_version": triage.PROMPT_VERSION, "created_at": "x"}
        for fid in ("nse:1", "nse:2")
    ], ("filing_id",))  # fmt: skip
    assert [r["id"] for r in triage.pending(conn, days=30)] == ["nse:1"]
