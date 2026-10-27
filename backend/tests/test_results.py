"""Results card maths, XBRL parsing and the screener.in check. No network."""

from datetime import date

import pytest

from finn.contracts import Metric, ResultsCard
from finn.enrich import results as R
from finn.enrich import xbrl
from finn.store import connect, upsert

XBRL = b"""<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:in-capmkt="http://example/capmkt"
            xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
  <xbrli:context id="OneD"><xbrli:period><xbrli:startDate>2026-07-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:context id="FourD"><xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:context id="Seg"><xbrli:entity><xbrli:segment><xbrldi:explicitMember dimension="d">m</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2026-07-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period></xbrli:context>
  <in-capmkt:NatureOfReportStandaloneConsolidated contextRef="OneD">Consolidated</in-capmkt:NatureOfReportStandaloneConsolidated>
  <in-capmkt:RevenueFromOperations contextRef="OneD" unitRef="INR">533555000000</in-capmkt:RevenueFromOperations>
  <in-capmkt:RevenueFromOperations contextRef="Seg" unitRef="INR">1</in-capmkt:RevenueFromOperations>
  <in-capmkt:Expenses contextRef="OneD" unitRef="INR">506190000000</in-capmkt:Expenses>
  <in-capmkt:FinanceCosts contextRef="OneD" unitRef="INR">677000000</in-capmkt:FinanceCosts>
  <in-capmkt:DepreciationDepletionAndAmortisationExpense contextRef="OneD" unitRef="INR">19599000000</in-capmkt:DepreciationDepletionAndAmortisationExpense>
  <in-capmkt:ProfitBeforeTax contextRef="OneD" unitRef="INR">31501000000</in-capmkt:ProfitBeforeTax>
  <in-capmkt:ProfitLossForPeriod contextRef="OneD" unitRef="INR">24661000000</in-capmkt:ProfitLossForPeriod>
  <in-capmkt:RevenueFromOperations contextRef="FourD" unitRef="INR">1058253000000</in-capmkt:RevenueFromOperations>
</xbrli:xbrl>"""


def test_xbrl_parse_picks_quarter_ytd_and_ignores_segments():
    fig = xbrl.parse(XBRL)
    assert fig.kind == "standard" and fig.basis == "consolidated"
    assert fig.quarter["revenue"] == pytest.approx(53355.5)  # rupees to crore, segment ignored
    assert fig.year_to_date["revenue"] == pytest.approx(105825.3)
    assert fig.ytd_start == date(2026, 4, 1)


def test_ebitda_matches_screener_definition():
    m = R.derive("standard", xbrl.parse(XBRL).quarter)
    # 53,355.5 - (50,619.0 - 67.7 - 1,959.9) = 4,764.1, screener.in's Operating Profit for Maruti
    assert m["ebitda"] == pytest.approx(4764.1, abs=0.05)


def test_bank_metrics():
    m = R.derive("bank", {"interest_earned": 11796.0, "interest_expended": 7226.5, "operating_profit": 2874.4,
                          "provisions": 1222.6, "pbt": 1651.8, "pat": 1241.8})  # fmt: skip
    assert m["nii"] == pytest.approx(4569.5)


@pytest.mark.parametrize(
    ("filed", "quarter", "label"),
    [(date(2026, 10, 27), date(2026, 9, 30), "Q2 FY27"), (date(2026, 1, 15), date(2025, 12, 31), "Q3 FY26"),
     (date(2026, 5, 2), date(2026, 3, 31), "Q4 FY26"), (date(2026, 7, 20), date(2026, 6, 30), "Q1 FY27")],
)  # fmt: skip
def test_periods(filed, quarter, label):
    assert R.quarter_end_before(filed) == quarter and R.fy_label(quarter) == label


def test_pct_and_percent_changes():
    assert R.pct(110, 100) == 10.0 and R.pct(-50, -100) == 50.0 and R.pct(1, 0) is None


def _card(pbt, ebitda=4764.1, assoc=None):
    metrics = [Metric(key=k, label=k, current=v, previous_quarter=None, year_ago=None, qoq_pct=None, yoy_pct=None)
               for k, v in (("revenue", 53355.5), ("ebitda", ebitda), ("pbt", pbt), ("pat", 2466.1))]  # fmt: skip
    return ResultsCard(symbol="X", period_end="2026-09-30", period_label="Q2 FY27", basis="consolidated",
                       kind="standard", metrics=metrics, source="xbrl", check_note="", source_urls=[],
                       share_of_associates=assoc)  # fmt: skip


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    rows = [
        ("Sales", 53356.0),
        ("Operating Profit", 4764.0),
        ("Profit before tax", 3219.0),
        ("Net Profit", 2466.0),
    ]
    upsert(c, "financials", [{"symbol": "X", "basis": "consolidated", "statement": "quarters", "period": "2026-09",
           "line_item": k, "value": v, "raw": str(v), "source_url": "u", "fetched_at": "t"} for k, v in rows],
           ("symbol", "basis", "statement", "period", "line_item"))  # fmt: skip
    return c


def test_check_allows_for_associates_outside_pbt(conn):
    card = R.check(conn, _card(pbt=3150.1, assoc=69.0))  # Maruti: associates shown below PBT
    assert card.verified is True and "associates" in card.check_note


def test_check_accepts_associates_already_inside_pbt(conn):
    card = R.check(conn, _card(pbt=3219.1, assoc=69.0))  # Mazagon-style presentation
    assert card.verified is True and "associates" not in card.check_note


def test_check_flags_a_real_mismatch(conn):
    card = R.check(conn, _card(pbt=2900.0))
    assert card.verified is False and "pbt" in card.check_note
