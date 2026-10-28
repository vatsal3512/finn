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


def test_only_rupee_amounts_are_converted():
    from finn.enrich.triage import ItemOut, amount_crore

    def item(value, unit, currency):
        return ItemOut(id="x", events=[], category="M&A", tier="glance", title="t", summary="s",
                       why_it_matters=None, sentiment="neutral", amount_value=value,
                       amount_unit=unit, amount_currency=currency)  # fmt: skip

    assert amount_crore(item(50, "billion", "USD")) is None  # Adani's market forecast
    assert amount_crore(item(42646.09, "million", "INR")) == 4264.61
    assert amount_crore(item(2.79, "crore", "Rs.")) == 2.79
    assert amount_crore(item(1250, "crore", None)) == 1250.0


def test_excerpt_ends_on_a_word_and_carries_later_amounts():
    from finn.enrich.triage import excerpt

    opening = "Pursuant to Regulation 30 we submit the details of notices received. " * 30
    annexure = (
        "Annexure A Name of the authority: Department of Telecommunications. Notice imposing "
        "a penalty of Rs.1,41,000 for alleged violation of subscriber verification norms."
    )
    out = excerpt(opening + annexure, limit=300)
    head = out.split(" …")[0]
    assert opening.startswith(head) and not head.endswith("receiv")  # cut on a word
    assert "Amounts later in the filing:" in out and "Rs.1,41,000" in out
    assert excerpt("Board meeting held today.", limit=300) == "Board meeting held today."


def test_a_wrong_share_of_revenue_is_corrected_and_a_fair_one_kept():
    from finn.enrich.triage import checked_shares

    polycab = "The amount is only ~0.00008% of its ₹34,609 crore revenue."
    assert checked_shares(polycab, 2.79, 34609) == (
        "The amount is only ~0.0081% of its ₹34,609 crore revenue."
    )
    ola = "The issue is over 50% of annual revenue (₹1,880 crore)."
    assert checked_shares(ola, 1000, 1880) == ola
    growth = "Revenue grew 30% while the order is small."
    assert checked_shares(growth, 50, 1000) == growth  # not a share of revenue


def test_results_numbers_only_for_results_filings_and_only_once_out(tmp_path):
    from finn.contracts import Metric, ResultsCard
    from finn.enrich import triage
    from finn.store import connect, upsert

    conn = connect(tmp_path / "t.db")
    card = ResultsCard(symbol="ADANIENT", period_end="2026-09-30", period_label="Q2 FY27",
                       basis="consolidated", kind="standard", source="xbrl", check_note="", source_urls=[],
                       metrics=[Metric(key="pat", label="Profit", current=1221.0, previous_quarter=430.7,
                                       year_ago=None, qoq_pct=183.5, yoy_pct=None)])  # fmt: skip
    upsert(conn, "results_cards", [{"symbol": "ADANIENT", "period_end": "2026-09-30",
           "basis": "consolidated", "kind": "standard", "card": card.model_dump_json(),
           "source": "xbrl", "created_at": "x"}], ("symbol", "period_end"))  # fmt: skip
    base = {"symbol": "ADANIENT", "exchange": "NSE", "needs_ai": 1, "source_url": "u",
            "fetched_at": "x", "exchange_label": "Press Release", "category": None}  # fmt: skip
    mou = {**base, "id": "nse:1", "filed_at": "2026-10-13T17:35:00+05:30",
           "headline": "press release titled Adani Enterprises, Jabil Sign MoU"}  # fmt: skip
    early = {**base, "id": "nse:2", "filed_at": "2026-10-13T18:00:00+05:30",
             "headline": "Earnings release for the quarter ended September 30, 2026"}  # fmt: skip
    statement = {**base, "id": "nse:3", "filed_at": "2026-10-28T16:00:00+05:30",
                 "category": "results", "headline": "Financial results for the quarter"}  # fmt: skip
    release = {**early, "id": "nse:4", "filed_at": "2026-10-28T16:30:00+05:30"}
    upsert(conn, "filings", [mou, early, statement, release], ("id",))
    row = lambda i: conn.execute("SELECT * FROM filings WHERE id = ?", (i,)).fetchone()  # noqa: E731

    assert triage._results_numbers(conn, row("nse:1")) is None  # not about results
    assert triage._results_numbers(conn, row("nse:2")) is None  # results not out yet
    assert "1,221.0" in triage._results_numbers(conn, row("nse:4"))


def _with_revenue(tmp_path, symbol, quarterly):
    from finn.store import connect, upsert

    conn = connect(tmp_path / "t.db")
    upsert(conn, "financials", [
        {"symbol": symbol, "basis": "consolidated", "statement": "quarters", "period": p,
         "line_item": "Sales", "value": quarterly, "raw": str(quarterly), "source_url": "s",
         "fetched_at": "x"}
        for p in ("2025-12", "2026-03", "2026-06", "2026-09")
    ], ("symbol", "basis", "statement", "period", "line_item"))  # fmt: skip
    return conn


def _answer(**kw):
    from finn.enrich.triage import ItemOut

    base = {"id": "nse:1", "events": [], "category": "fund_raise", "tier": "glance",
            "title": "t", "summary": "s", "why_it_matters": None, "sentiment": "neutral"}  # fmt: skip
    return ItemOut(**{**base, **kw})


def test_review_lifts_a_large_raise_to_must_see_and_never_lowers_by_size(tmp_path):
    from finn.enrich.triage import review

    conn = _with_revenue(tmp_path, "OLAELEC", 470)  # about ₹1,880 crore a year
    ola = _answer(amount_value=1000, amount_unit="crore", amount_currency="INR")
    assert review(conn, "OLAELEC", ola, "rights issue of up to ₹1,000 crore") == 1000
    assert ola.tier == "must_see"
    claim = _answer(category="litigation", tier="must_see", amount_value=2.79, amount_unit="crore")
    review(conn, "OLAELEC", claim, "claim of Rs 2.79 crore")
    assert claim.tier == "must_see"  # small, but not lowered


def test_review_drops_amounts_that_are_not_money_and_unverifiable_lines(tmp_path):
    from finn.enrich.triage import review

    conn = _with_revenue(tmp_path, "ADANIENT", 27858)
    jio = _answer(amount_value=270000000, amount_unit="crore")  # a share count, read as rupees
    assert review(conn, "ADANIENT", jio, "27,00,00,000 (Twenty seven crore) equity shares") is None
    summed = _answer(
        category="credit_rating", why_it_matters="Covers facilities totalling Rs 25,749.96 crore."
    )
    review(conn, "ADANIENT", summed, "bank facilities 16,505.00; 4,000.00; 240.00; 954.96")
    assert summed.why_it_matters is None
    fair = _answer(why_it_matters="The raise of ₹1,000 crore is about 1% of annual revenue.",
                   amount_value=1000, amount_unit="crore")  # fmt: skip
    review(conn, "ADANIENT", fair, "rights issue of up to ₹1,000 crore")
    assert (
        fair.why_it_matters == "The raise of ₹1,000 crore is about 1% of annual revenue."
    )  # fair rounding kept


def test_important_filing_answered_by_the_groq_fallback_is_asked_again(tmp_path):
    from finn.enrich import triage
    from finn.store import connect, upsert

    conn = connect(tmp_path / "t.db")
    base = {"symbol": "OLAELEC", "exchange": "NSE", "filed_at": "2099-01-01T10:00:00+05:30",
            "needs_ai": 1, "tier": "glance", "source_url": "u", "fetched_at": "x"}  # fmt: skip
    upsert(conn, "filings", [{**base, "id": "nse:1", "category": "fund_raise"},
                             {**base, "id": "nse:2", "category": "other"}], ("id",))  # fmt: skip
    upsert(conn, "filing_insights", [
        {"filing_id": fid, "model": triage.GROQ_MODEL, "prompt_version": triage.PROMPT_VERSION,
         "created_at": "x"} for fid in ("nse:1", "nse:2")
    ], ("filing_id",))  # fmt: skip
    todo = triage.pending(conn, days=30)
    assert [r["id"] for r in todo] == ["nse:1"] and triage._reask(todo[0])
