"""Results numbers from XBRL: the machine-readable copy companies file with each result.

This is the first and best rung of the results ladder (decision D14). The numbers are
exactly what the company filed, need no OCR or model, and cost nothing.

Where to find them
- NSE's "Integrated Filing - Financials" holds results from the March 2025 quarter on.
- NSE's older financial-results feed holds earlier quarters.

What a file holds: the quarter itself and the year to date. The previous quarter is
therefore the year to date minus this quarter, when they share a financial year. The
same quarter last year comes from last year's file.

Two taxonomies matter. Companies use the Ind AS format; banks use the banking format,
which has no revenue or EBITDA, so the bank card uses net interest income and operating
profit before provisions instead.

XBRL can lag the PDF by hours: Maruti's Q2 FY27 PDF was filed at 15:24 and its XBRL at
19:31 on the same day. Until it arrives, the ladder reads the PDF instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from lxml import etree

from finn import net

log = logging.getLogger(__name__)

INTEGRATED_API = "https://www.nseindia.com/api/integrated-filing-results"
LEGACY_API = "https://www.nseindia.com/api/corporates-financial-results"
XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"
CRORE = 1e7

STANDARD_TAGS = {
    "revenue": "RevenueFromOperations",
    "other_income": "OtherIncome",
    "total_expenses": "Expenses",
    "finance_costs": "FinanceCosts",
    "depreciation": "DepreciationDepletionAndAmortisationExpense",
    "pbt": "ProfitBeforeTax",
    "pat": "ProfitLossForPeriod",
    "associates": "ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod",
}
BANK_TAGS = {
    "interest_earned": "InterestEarned",
    "interest_expended": "InterestExpended",
    "total_income": "Income",
    "operating_profit": "OperatingProfitBeforeProvisionAndContingencies",
    "provisions": "ProvisionsOtherThanTaxAndContingencies",
    "pbt": "ProfitLossFromOrdinaryActivitiesBeforeTax",
    "pat": "ProfitLossForThePeriod",
    "associates": "ShareOfProfitLossOfAssociates",
}


@dataclass(frozen=True)
class XbrlFiling:
    symbol: str
    period_end: date
    basis: str  # consolidated | standalone
    url: str
    filed_at: str
    revised: bool


@dataclass
class XbrlFigures:
    period_end: date
    basis: str
    kind: str  # standard | bank
    quarter: dict[str, float] = field(default_factory=dict)  # in rupees crore
    year_to_date: dict[str, float] = field(default_factory=dict)
    ytd_start: date | None = None
    source_url: str = ""


def _d(s: str, fmt: str) -> date:
    return datetime.strptime(s.strip(), fmt).date()


def list_filings(symbol: str) -> list[XbrlFiling]:
    """Every results XBRL NSE has for a company, newest first, from both feeds."""
    out: list[XbrlFiling] = []
    page, seen = 1, 0
    while page <= 5:
        data = net.nse().get_json(
            INTEGRATED_API, {"index": "equities", "symbol": symbol, "page": page}
        )
        rows = data.get("data", []) if isinstance(data, dict) else []
        for r in rows:
            if not str(r.get("type", "")).startswith("Integrated Filing- Financials") or not r.get(
                "xbrl"
            ):
                continue
            out.append(
                XbrlFiling(
                    symbol=symbol,
                    period_end=_d(r["qe_Date"], "%d-%b-%Y"),
                    basis=str(r.get("consolidated", ""))
                    .lower()
                    .replace("non-consolidated", "standalone"),
                    url=r["xbrl"],
                    filed_at=r.get("broadcast_Date") or "",
                    revised=str(r.get("type_Sub", "")).lower() != "original",
                )
            )
        seen += len(rows)
        total = data.get("totalCount", 0) if isinstance(data, dict) else 0
        if not rows or seen >= total:
            break
        page += 1
    try:
        legacy = net.nse().get_json(
            LEGACY_API, {"index": "equities", "period": "Quarterly", "symbol": symbol}
        )
    except (net.HTTPError, net.TransientHTTPError) as exc:
        log.info("legacy results feed failed for %s: %s", symbol, exc)
        legacy = []
    for r in legacy if isinstance(legacy, list) else []:
        if r.get("xbrl") and r.get("toDate"):
            basis = "consolidated" if str(r.get("consolidated")) == "Consolidated" else "standalone"
            out.append(
                XbrlFiling(
                    symbol,
                    _d(r["toDate"], "%d-%b-%Y"),
                    basis,
                    r["xbrl"],
                    r.get("broadCastDate") or "",
                    False,
                )
            )
    # Revised filings supersede originals for the same period and basis.
    out.sort(key=lambda f: (f.period_end, f.basis, f.revised, f.filed_at), reverse=True)
    unique: dict[tuple[date, str], XbrlFiling] = {}
    for f in out:
        unique.setdefault((f.period_end, f.basis), f)
    return sorted(unique.values(), key=lambda f: f.period_end, reverse=True)


def parse(xml: bytes, source_url: str = "") -> XbrlFigures:
    root = etree.fromstring(xml)
    contexts: dict[str, tuple[date | None, date | None]] = {}
    for cx in root.iter(f"{{{XBRLI}}}context"):
        if next(cx.iter(f"{{{XBRLDI}}}explicitMember"), None) is not None:
            continue  # dimensional contexts hold breakdowns, not the headline totals
        start = cx.findtext(f".//{{{XBRLI}}}startDate")
        end = cx.findtext(f".//{{{XBRLI}}}endDate")
        if start and end:
            contexts[cx.get("id")] = (date.fromisoformat(start), date.fromisoformat(end))
    facts: dict[str, dict[str, float]] = {}
    basis = "consolidated"
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        name = etree.QName(el).localname
        if name == "NatureOfReportStandaloneConsolidated" and el.text:
            basis = el.text.strip().lower()
        ref = el.get("contextRef")
        if ref in contexts and el.get("unitRef") == "INR" and el.text:
            try:
                facts.setdefault(ref, {})[name] = float(el.text) / CRORE
            except ValueError:
                continue
    if not contexts:
        raise ValueError("no duration contexts in XBRL")
    end = max(e for _, e in contexts.values())
    spans = {ref: (s, e) for ref, (s, e) in contexts.items() if e == end and ref in facts}
    quarter_ref = min(spans, key=lambda r: (spans[r][1] - spans[r][0]).days)
    ytd_ref = max(spans, key=lambda r: (spans[r][1] - spans[r][0]).days)
    all_names = set().union(*facts.values())
    kind = "bank" if "InterestEarned" in all_names else "standard"
    tags = BANK_TAGS if kind == "bank" else STANDARD_TAGS
    pick = lambda ref: {k: facts[ref][t] for k, t in tags.items() if t in facts.get(ref, {})}  # noqa: E731
    return XbrlFigures(
        period_end=end,
        basis=basis,
        kind=kind,
        quarter=pick(quarter_ref),
        year_to_date=pick(ytd_ref) if ytd_ref != quarter_ref else {},
        ytd_start=spans[ytd_ref][0] if ytd_ref != quarter_ref else None,
        source_url=source_url,
    )


def fetch(filing: XbrlFiling) -> XbrlFigures:
    return parse(net.nse().get_bytes(filing.url), filing.url)
