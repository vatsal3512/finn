"""Research: quotes are checked, periods parsed, promises graded by code, cash computed.

The figures are Kaynes Technology's and Infosys's own, from their calls and accounts.
"""

import pytest

from finn.research import cash, periods
from finn.research.engine import _call_label, _prose, model_verdict
from finn.research.extract import Call, Claim, Verified
from finn.research.judge import Ruling
from finn.research.quotes import Document
from finn.research.score import Actuals, compare, drafts, target_text
from finn.store import connect, upsert

HEADER = "Kaynes Technology India Limited\nAugust 08, 2026\nPage {n} of 19\n"


def _transcript() -> Document:
    pages = [
        HEADER.format(n=i) + f"Filler line number {i} about the business." for i in range(1, 7)
    ]
    pages[2] = (
        HEADER.format(n=3)
        + "Our total revenue stood at INR946 crores, reflecting an year-on-year growth of 40%, which"
    )
    pages[3] = (
        HEADER.format(n=4)
        + "is largely driven by EMS business. We have committed a full year revenue of totally"
    )
    pages[4] = HEADER.format(n=5) + "INR500 crores between both, which is what we are targeting."
    return Document("Q1 FY27 call, 8 Aug 2026", "https://example/t.pdf", pages)


# ---------------------------------------------------------------- quotes


def test_quote_found_despite_spacing_and_page_header_mid_sentence():
    doc = _transcript()
    m = doc.find(
        "Our total revenue stood at INR 946 crores, reflecting an year-on-year growth of 40%"
    )
    assert m and m.exact and m.page == 3 and m.text.endswith("40%")
    m = doc.find("We have committed a full year revenue of totally INR500 crores between both")
    assert m and m.page == 4 and "Page" not in m.text  # the running header is gone


def test_small_slip_matches_but_shows_the_documents_words():
    m = _transcript().find(
        "We have committed the full year revenue of totally INR500 crores between both"
    )
    assert m and not m.exact and m.text.startswith("We have committed a full year")


def test_invented_quote_is_rejected():
    assert _transcript().find("We will grow revenue by 60% this year with margins of 18%") is None


# ---------------------------------------------------------------- periods


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("FY27", ("2027-03", "year")),
        ("FY2026-27", ("2027-03", "year")),
        ("Q1 FY27", ("2026-06", "quarter")),
        ("Q4 FY26", ("2026-03", "quarter")),
        ("H2 FY27", ("2027-03", "half")),
        ("9M FY27", ("2026-12", "nine_months")),
        ("by March", None),
        (None, None),
    ],
)
def test_indian_financial_year_periods(label, expected):
    assert periods.parse(label) == expected


# ---------------------------------------------------------------- grading


def _actuals(tmp_path, symbol="KAYNES", bank=False):
    conn = connect(tmp_path / "t.db")
    rows = []

    def add(st, item, period, value):
        rows.append({"symbol": symbol, "basis": "consolidated", "statement": st, "period": period,
                     "line_item": item, "value": value, "raw": str(value), "source_url": "s",
                     "fetched_at": "x"})  # fmt: skip

    for period, sales, pat, cfo, fcf, debtor, wc in (
        ("2022-03", 706, 42, 21, -21, 102, 53), ("2023-03", 1126, 95, -42, -100, 74, 107),
        ("2024-03", 1805, 183, 88, -295, 72, 66), ("2025-03", 2722, 293, -82, -1031, 77, -7),
        ("2026-03", 3626, 364, -600, -1841, 154, 133),
    ):  # fmt: skip
        add("profit_loss", "Sales", period, sales)
        add("profit_loss", "Net Profit", period, pat)
        add("profit_loss", "Operating Profit", period, sales * 0.16)
        add("profit_loss", "Depreciation", period, sales * 0.03)
        add("cash_flow", "Cash from Operating Activity", period, cfo)
        add("cash_flow", "Free Cash Flow", period, fcf)
        add("ratios", "Debtor Days", period, debtor)
        add("ratios", "Working Capital Days", period, wc)
    add("quarters", "Sales", "2026-06", 946)
    upsert(conn, "financials", rows, ("symbol", "basis", "statement", "period", "line_item"))
    return Actuals(conn, symbol)


def _claim(**kw) -> Claim:
    base = {"kind": "guidance", "metric_key": "revenue", "metric": "Revenue", "scope": "company",
            "period": "FY26", "low": None, "high": None, "unit": None, "basis": None,
            "statement": "s", "quote": "q", "speaker": "CFO"}  # fmt: skip
    return Claim(**{**base, **kw})


def _call(claims, period="2026-02") -> Call:
    call = Call(Document("call", "u", ["x"]), period, "Q3 FY26 call", None, True, None)
    call.claims = [Verified(c, c.quote, 1, True) for c in claims]
    return call


def _grade(tmp_path, claim, outcomes=()):
    act = _actuals(tmp_path)
    calls = [_call([claim]), _call(list(outcomes), "2026-05")] if outcomes else [_call([claim])]
    return drafts(calls, act)[0].grade


def test_kaynes_fy26_revenue_promise_is_graded_missed_by_code(tmp_path):
    # Feb 2026: "we'll cross about INR4,000 crores minimum". FY26 came in at ₹3,626 crore.
    g = _grade(tmp_path, _claim(low=4000, unit="crore"))
    assert g.verdict == "missed" and g.actual == "₹3,626 crore"


def test_operating_cash_flow_promise_is_graded_by_sign(tmp_path):
    c = _claim(metric_key="cash_flow", statement="Operating cash flow will be positive by FY26 end")
    g = _grade(tmp_path, c)
    assert g.verdict == "missed" and g.actual.startswith("−₹600 crore")


def test_working_capital_days_lower_is_better(tmp_path):
    g = _grade(tmp_path, _claim(metric_key="working_capital_days", low=70, high=85, unit="days"))
    assert g.verdict == "missed" and g.actual == "133 days"


def test_ebit_margin_is_operating_profit_less_depreciation(tmp_path):
    # Infosys guides on operating (EBIT) margin; comparing with EBITDA would call it beaten.
    g = _grade(tmp_path, _claim(metric_key="ebit_margin", low=12, high=14, unit="%"))
    assert g.verdict == "met" and g.actual == "13.0%"


def test_segment_targets_are_not_graded_against_company_numbers(tmp_path):
    assert _grade(tmp_path, _claim(scope="segment", low=450, high=500, unit="crore")) is None


def test_future_period_is_pending(tmp_path):
    assert _grade(tmp_path, _claim(period="FY27", low=4500, unit="crore")).verdict == "pending"


def test_constant_currency_guidance_uses_managements_later_statement(tmp_path):
    guide = _claim(
        metric_key="revenue_growth", low=3, high=3.5, unit="%", basis="constant currency"
    )
    outcome = _claim(kind="outcome", metric_key="revenue_growth", low=3.1, high=3.1, unit="%",
                     basis="constant currency", quote="We had growth of 3.1% for the full year")  # fmt: skip
    g = _grade(tmp_path, guide, [outcome])
    assert g.verdict == "met" and g.actual == "3.1%" and g.by_outcome.quote.startswith("We had")


def test_repeated_promise_is_folded_into_the_first(tmp_path):
    act = _actuals(tmp_path)
    c = _claim(period="FY28", low=1, high=1, unit="billion", basis="USD")
    ds = drafts([_call([c], "2026-02"), _call([c.model_copy()], "2026-05")], act)
    assert len(ds) == 1 and len(ds[0].repeated_in) == 1


@pytest.mark.parametrize(
    ("low", "high", "actual", "verdict"),
    [
        (4000, None, 3626, "missed"),
        (15, 17, 16, "met"),
        (15, 17, 18, "beat"),
        (20, 22, 21.6, "met"),
    ],
)
def test_compare(low, high, actual, verdict):
    assert compare(low, high, actual, 0.5) == verdict


def test_target_text():
    assert target_text(_claim(low=4000, unit="crore")) == "≥ ₹4,000 crore"
    assert (
        target_text(_claim(low=1.5, high=3, unit="%", basis="constant currency"))
        == "1.5–3% (constant currency)"
    )
    assert target_text(_claim(low=0, unit="crore")) == "positive"


# ---------------------------------------------------------------- cash quality


def test_cash_quality_states_the_kaynes_gap(tmp_path):
    q = cash.compute(_actuals(tmp_path), is_bank=False)
    assert q.applicable and q.conversion_5y == round(-615 / 977, 2)
    text = " ".join(s.quote for s in q.signals)
    assert "−₹615 crore" in text and "FY23, FY25, FY26" in text and "rose from 72 to 154" in text


def test_cash_quality_does_not_apply_to_banks(tmp_path):
    q = cash.compute(_actuals(tmp_path, "HDFCBANK"), is_bank=True)
    assert not q.applicable and "bank" in q.reason


# ---------------------------------------------------------------- the judge's limits


def test_a_promise_is_not_evidence_for_itself(tmp_path):
    act = _actuals(tmp_path)
    verdict, others, _ = model_verdict(Ruling(id="C3", verdict="on_track", evidence=["C3"]), "C3",
                                       _claim(period="FY28"), act)  # fmt: skip
    assert verdict == "pending" and others == []


def test_no_miss_before_the_deadline(tmp_path):
    act = _actuals(tmp_path)
    verdict, _, _ = model_verdict(Ruling(id="C3", verdict="missed", evidence=["C9"]), "C3",
                                  _claim(period="FY28"), act)  # fmt: skip
    assert verdict == "at_risk"


def test_over_and_unreported_is_unclear_and_filler_notes_go(tmp_path):
    act = _actuals(tmp_path)
    verdict, _, note = model_verdict(
        Ruling(id="C3", verdict="pending", note="Applies to the full year.", evidence=[]), "C3",
        _claim(period="FY26", scope="segment"), act,
    )  # fmt: skip
    assert verdict == "unclear" and note is None


def test_ids_never_reach_prose():
    assert (
        _prose("grew 40% (C31), cash fell (F1, F3). FY27 holds")
        == "grew 40%, cash fell. FY27 holds"
    )


def test_investor_day_is_not_labelled_an_earnings_call():
    call = Call(
        Document("x", "u", ["x"]), "2026-02", "Investor AI Day 2026", "2026-02-17", False, None
    )
    assert _call_label(call) == "Investor day, 17 Feb 2026"


def test_open_ended_promise_cannot_be_finally_met(tmp_path):
    # Titan: "jewellery EBIT margin of about 11%", no period. Q1 at 10.9% is on track, not met.
    verdict, _, _ = model_verdict(Ruling(id="C3", verdict="met", evidence=["C9"]), "C3",
                                  _claim(period=None), _actuals(tmp_path))  # fmt: skip
    assert verdict == "on_track"


def test_a_later_periods_number_does_not_put_an_ended_promise_on_track(tmp_path):
    verdict, _, _ = model_verdict(Ruling(id="C3", verdict="on_track", evidence=["C9"]), "C3",
                                  _claim(period="FY26", scope="segment"), _actuals(tmp_path))  # fmt: skip
    assert verdict == "unclear"


def _quarters(tmp_path):
    act = _actuals(tmp_path)
    for period, sales in (("2025-03", 801), ("2025-12", 1211), ("2026-03", 1824)):  # HFCL's
        act.values[("quarters", "Sales", period)] = sales
    act.latest["quarters"] = "2026-06"
    return act


def test_quarter_growth_with_no_stated_comparison_is_not_graded(tmp_path):
    # HFCL, Feb 2026: "revenue in this current quarter ... somewhere around 10% to 15%".
    c = _claim(metric_key="revenue_growth", period="Q4 FY26", low=10, high=15, unit="%")
    assert drafts([_call([c])], _quarters(tmp_path))[0].grade is None


def test_sequential_growth_is_compared_with_the_quarter_before(tmp_path):
    c = _claim(metric_key="revenue_growth", period="Q4 FY26", low=10, high=15, unit="%",
               compared_with="previous_period")  # fmt: skip
    g = drafts([_call([c])], _quarters(tmp_path))[0].grade
    assert g.verdict == "beat" and g.actual == "50.6%"  # 1,824 against 1,211


def test_volume_growth_is_never_graded_against_revenue(tmp_path):
    c = _claim(metric_key="volume_growth", period="FY26", low=8, high=10, unit="%")
    assert drafts([_call([c])], _actuals(tmp_path))[0].grade is None


def test_amounts_in_prose_read_as_rupees_in_crore():
    assert _prose("missed over 4,000 crore rupees; cash was negative 600 crore rupees") == (
        "missed over ₹4,000 crore; cash was −₹600 crore"
    )
    assert _prose("revenue of INR 3,626.4 crores, cash negative ₹615 crore") == (
        "revenue of ₹3,626.4 crore, cash −₹615 crore"
    )


def test_rupee_targets_show_in_crore_and_cash_promises_as_positive():
    assert target_text(_claim(low=40000, unit="million")) == "≥ ₹4,000 crore"
    c = _claim(metric_key="cash_flow", statement="Operating cash flow will be positive by FY26 end")
    assert target_text(c) == "positive"


def test_dollar_targets_read_in_dollars():
    assert target_text(_claim(low=1000, unit="million USD", basis="USD")) == "≥ $1,000 million"
    assert target_text(_claim(low=1, high=1, unit="billion", basis="USD")) == "$1 billion"
