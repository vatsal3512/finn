"""The results card: headline numbers for a quarter, versus last quarter and a year ago.

The ladder (decision D14), tried in order until one rung works:
1. XBRL from the exchange. Exact, free and needs no model.
2. The results PDF's text, read by a model, when the text layer is clean.
3. The results PDF's pages as images, read by a vision model, when the text is garbled.
4. screener.in's quarterly table, labelled as not checked against the filing.

Every card from rungs 1 to 3 is compared with screener.in. A match within 2% earns the
verified badge; a mismatch is shown, not hidden.

Arithmetic is done here in code, never by a model: EBITDA, percentage changes, margins
and unit conversion.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, timedelta

from pydantic import BaseModel, Field

from finn.ai.llm import LLM, AIUnavailable, Tier
from finn.config import DATA_DIR
from finn.contracts import Metric, ResultsCard
from finn.enrich import xbrl
from finn.pdftext import find_pages, load_pages, render_pages
from finn.store import now_iso

log = logging.getLogger(__name__)

TOLERANCE = 0.02
PROMPT_VERSION = "results-v1"

STANDARD = (
    ("revenue", "Revenue"),
    ("ebitda", "EBITDA"),
    ("pbt", "Profit before tax"),
    ("pat", "Profit after tax"),
)
BANK = (
    ("nii", "Net interest income"),
    ("operating_profit", "Operating profit before provisions"),
    ("provisions", "Provisions"),
    ("pbt", "Profit before tax"),
    ("pat", "Profit after tax"),
)
SCREENER_ITEMS = {  # our metric -> screener.in quarterly line items, first match wins
    "revenue": ("Sales", "Revenue"),
    "ebitda": ("Operating Profit",),
    "pbt": ("Profit before tax",),
    "pat": ("Net Profit",),
    "interest_earned": ("Revenue",),
}


# ---------------------------------------------------------------- periods


def quarter_end_before(d: date) -> date:
    """The last quarter end strictly before a date: results filed in October cover September."""
    for month, day in ((12, 31), (9, 30), (6, 30), (3, 31)):
        q = date(d.year, month, day)
        if q < d:
            return q
    return date(d.year - 1, 12, 31)


def previous_quarter_end(q: date) -> date:
    return quarter_end_before(q)


def fy_label(q: date) -> str:
    fy = q.year + 1 if q.month > 3 else q.year
    quarter = {6: 1, 9: 2, 12: 3, 3: 4}[q.month]
    return f"Q{quarter} FY{fy % 100:02d}"


# ---------------------------------------------------------------- metric maths


def derive(kind: str, raw: dict[str, float]) -> dict[str, float | None]:
    """Card metrics from raw line items, in rupees crore."""
    g = raw.get
    if kind == "bank":
        nii = (
            g("interest_earned") - g("interest_expended")
            if g("interest_earned") is not None and g("interest_expended") is not None
            else None
        )
        return {
            "nii": nii,
            "operating_profit": g("operating_profit"),
            "provisions": g("provisions"),
            "pbt": g("pbt"),
            "pat": g("pat"),
            "interest_earned": g("interest_earned"),
            "associates": g("associates"),
        }
    ebitda = None
    if (
        g("revenue") is not None
        and g("total_expenses") is not None
        and g("finance_costs") is not None
        and g("depreciation") is not None
    ):
        # Same definition as screener.in's Operating Profit: revenue minus operating costs,
        # where operating costs exclude interest and depreciation. Unlike PBT-based
        # formulas, it is not thrown off by exceptional items or associates' profits.
        ebitda = g("revenue") - (g("total_expenses") - g("finance_costs") - g("depreciation"))
    return {"revenue": g("revenue"), "ebitda": ebitda, "pbt": g("pbt"), "pat": g("pat"),
            "associates": g("associates")}  # fmt: skip


def pct(new: float | None, old: float | None) -> float | None:
    if new is None or old is None or old == 0:
        return None
    return round((new - old) / abs(old) * 100, 1)


def make_card(symbol, period_end, basis, kind, cur, prev, yago, source, source_urls) -> ResultsCard:
    spec = BANK if kind == "bank" else STANDARD
    metrics = [
        Metric(
            key=k,
            label=label,
            current=_r(cur.get(k)),
            previous_quarter=_r(prev.get(k)) if prev else None,
            year_ago=_r(yago.get(k)) if yago else None,
            qoq_pct=pct(cur.get(k), prev.get(k) if prev else None),
            yoy_pct=pct(cur.get(k), yago.get(k) if yago else None),
        )
        for k, label in spec
    ]
    margin_label, margins = None, []
    if kind == "standard":
        margin_label = "EBITDA margin"
        margins = [_margin(d) for d in (cur, prev or {}, yago or {})]
    return ResultsCard(
        symbol=symbol, period_end=period_end.isoformat(), period_label=fy_label(period_end), basis=basis,
        kind=kind, metrics=metrics, margin_label=margin_label, margin_pct=margins, source=source,
        verified=None, check_note="", source_urls=source_urls,
        share_of_associates=_r(cur.get("associates")) or None,
    )  # fmt: skip


def _margin(d: dict) -> float | None:
    if d.get("ebitda") is None or not d.get("revenue"):
        return None
    return round(d["ebitda"] / d["revenue"] * 100, 1)


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 1)


# ---------------------------------------------------------------- rung 1: XBRL


def from_xbrl(symbol: str, period_end: date) -> ResultsCard | None:
    filings = xbrl.list_filings(symbol)
    by_key = {(f.period_end, f.basis): f for f in filings}
    for basis in ("consolidated", "standalone"):
        current = by_key.get((period_end, basis))
        if not current:
            continue
        cur_fig = xbrl.fetch(current)
        kind = cur_fig.kind
        prev_q, yago_q = (
            previous_quarter_end(period_end),
            date(period_end.year - 1, period_end.month, period_end.day),
        )
        prev = by_key.get((prev_q, basis))
        yago = by_key.get((yago_q, basis))
        prev_raw = xbrl.fetch(prev).quarter if prev else _ytd_minus_quarter(cur_fig)
        yago_raw = xbrl.fetch(yago).quarter if yago else None
        urls = [current.url] + [f.url for f in (prev, yago) if f]
        return make_card(symbol, period_end, basis, kind, derive(kind, cur_fig.quarter),
                         derive(kind, prev_raw) if prev_raw else None,
                         derive(kind, yago_raw) if yago_raw else None, "xbrl", urls)  # fmt: skip
    return None


def _ytd_minus_quarter(fig: xbrl.XbrlFigures) -> dict[str, float] | None:
    """Previous quarter as year-to-date minus this quarter, for a six-month year to date."""
    if not fig.year_to_date or not fig.ytd_start or (fig.period_end - fig.ytd_start).days > 200:
        return None
    return {k: fig.year_to_date[k] - fig.quarter[k] for k in fig.quarter if k in fig.year_to_date}


# ---------------------------------------------------------------- rungs 2 and 3: the PDF


class Column(BaseModel):
    label: str = Field(description="Column heading as printed, e.g. 'Quarter ended 30.09.2026'")
    period_end: str = Field(description="End date of the column's period, YYYY-MM-DD")
    months: int = Field(description="Length of the period in months: 3, 6, 9 or 12")
    revenue: float | None = Field(None, description="Revenue from operations")
    other_income: float | None = None
    total_expenses: float | None = Field(
        None, description="Total expenses, including finance costs and depreciation"
    )
    finance_costs: float | None = None
    depreciation: float | None = Field(None, description="Depreciation and amortisation")
    pbt: float | None = Field(None, description="Profit before tax, after exceptional items")
    pat: float | None = Field(None, description="Net profit for the period")
    interest_earned: float | None = Field(None, description="Banks only")
    interest_expended: float | None = Field(None, description="Banks only")
    operating_profit: float | None = Field(
        None, description="Banks only: operating profit before provisions"
    )
    provisions: float | None = Field(None, description="Banks only: provisions other than tax")


class Statement(BaseModel):
    basis: str = Field(description="consolidated or standalone")
    unit: str = Field(
        description="Unit stated on the statement: rupees, thousand, lakh, million or crore"
    )
    is_bank: bool
    columns: list[Column]


UNIT_TO_CRORE = {"crore": 1.0, "million": 0.1, "lakh": 0.01, "thousand": 1e-4, "rupees": 1e-7}

SYSTEM = (
    "You read Indian listed companies' quarterly results statements. Copy numbers exactly "
    "as printed. Never calculate, estimate or round. Brackets mean negative. If a value is "
    "not printed, leave it null. Prefer the consolidated statement when both are present."
)


def _unit_factor(unit: str) -> float:
    u = unit.lower()
    for name, factor in UNIT_TO_CRORE.items():
        if name in u:
            return factor
    return 1.0 if "cr" in u else 0.01 if "lac" in u else 1.0


def _statement_pages(pages: list[str]) -> list[int]:
    hits = find_pages(
        pages, r"revenue from operations|interest earned|statement of .{0,40}results", limit=6
    )
    return hits[:3] or list(range(1, min(len(pages), 3) + 1))


def from_filing(
    conn: sqlite3.Connection, llm: LLM, filing: sqlite3.Row, period_end: date
) -> ResultsCard | None:
    if not filing["text_path"]:
        return None
    pages = load_pages(DATA_DIR / filing["text_path"])
    picks = _statement_pages(pages)
    if filing["text_quality"] == "ok":
        prompt = "Extract the results statement.\n\n" + "\n\n".join(
            f"--- page {n} ---\n{pages[n - 1][:9000]}" for n in picks
        )
        stmt = llm.json(
            "results_text", Tier.FLASH, prompt, Statement, system=SYSTEM, version=PROMPT_VERSION
        )
        source = "filing_text"
    elif filing["pdf_path"]:
        images = render_pages((DATA_DIR / filing["pdf_path"]).read_bytes(), picks)
        prompt = "These are pages of a quarterly results filing. Extract the results statement."
        stmt = llm.json(
            "results_image",
            Tier.FLASH,
            prompt,
            Statement,
            system=SYSTEM,
            version=PROMPT_VERSION,
            images=images,
        )
        source = "filing_image"
    else:
        return None
    factor = _unit_factor(stmt.unit)
    quarters = {c.period_end[:7]: c for c in stmt.columns if c.months == 3}
    wanted = [
        period_end,
        previous_quarter_end(period_end),
        date(period_end.year - 1, period_end.month, period_end.day),
    ]
    cols = [quarters.get(d.isoformat()[:7]) for d in wanted]
    if cols[0] is None:
        raise ValueError(f"statement has no column for the quarter ending {period_end}")
    kind = "bank" if stmt.is_bank else "standard"
    raws = [
        {k: v * factor for k, v in c.model_dump(exclude={"label", "period_end", "months"}).items() if v is not None} if c else None
        for c in cols
    ]  # fmt: skip
    return make_card(filing["symbol"], period_end, stmt.basis.lower(), kind, derive(kind, raws[0]),
                     derive(kind, raws[1]) if raws[1] else None, derive(kind, raws[2]) if raws[2] else None,
                     source, [filing["attachment_url"]])  # fmt: skip


# ---------------------------------------------------------------- rung 4 and the check


def screener_quarter(
    conn: sqlite3.Connection, symbol: str, period: date, basis: str | None = None
) -> dict[str, float]:
    rows = conn.execute(
        "SELECT basis, line_item, value FROM financials WHERE symbol = ? AND statement = 'quarters' AND period = ?",
        (symbol, period.isoformat()[:7]),
    ).fetchall()
    if basis:
        rows = [r for r in rows if r["basis"] == basis] or rows
    items = {r["line_item"]: r["value"] for r in rows if r["value"] is not None}
    out = {}
    for metric, names in SCREENER_ITEMS.items():
        for n in names:
            if n in items:
                out[metric] = items[n]
                break
    return out


def from_screener(
    conn: sqlite3.Connection, symbol: str, period_end: date, is_bank: bool
) -> ResultsCard | None:
    cur = screener_quarter(conn, symbol, period_end)
    if not cur:
        return None
    prev = screener_quarter(conn, symbol, previous_quarter_end(period_end))
    yago = screener_quarter(
        conn, symbol, date(period_end.year - 1, period_end.month, period_end.day)
    )
    url = conn.execute("SELECT screener_url FROM companies WHERE symbol = ?", (symbol,)).fetchone()
    kind = "bank" if is_bank else "standard"
    if kind == "bank":  # screener.in's bank table has no NII split, so show what it has
        cur, prev, yago = ({"pbt": d.get("pbt"), "pat": d.get("pat")} for d in (cur, prev, yago))
    card = make_card(symbol, period_end, "consolidated", kind, cur, prev or None, yago or None, "screener",
                     [url["screener_url"]] if url and url["screener_url"] else [])  # fmt: skip
    card.check_note = "From screener.in. Not yet checked against the company's own filing."
    return card


def check(conn: sqlite3.Connection, card: ResultsCard) -> ResultsCard:
    if card.source == "screener":
        return card
    ref = screener_quarter(conn, card.symbol, date.fromisoformat(card.period_end), card.basis)
    current = {m.key: m.current for m in card.metrics}
    # The share of associates' profit is presented differently by different companies, and
    # screener.in normalises it into its own lines (a profit into other income, a loss into
    # expenses, both into PBT). Maruti's Q2 FY27 filing shows its +69 crore below PBT;
    # Mazagon Dock's +48.5 crore is already inside PBT. So each figure is accepted under
    # either presentation, and the note says which one matched.
    assoc = card.share_of_associates or 0.0
    alternatives = {
        "pbt": [0.0, assoc] if assoc else [0.0],
        "ebitda": [0.0, assoc] if assoc < 0 else [0.0],
    }
    compared, off, adjusted = [], [], []
    for k in ("revenue", "ebitda", "pbt", "pat"):
        a, b = current.get(k), ref.get(k)
        if a is None or b is None:
            continue
        compared.append(k)
        ok = [
            adj
            for adj in alternatives.get(k, [0.0])
            if abs(a + adj - b) <= max(1.0, TOLERANCE * abs(b))
        ]
        if not ok:
            off.append((k, a, b))
        elif ok[0]:
            adjusted.append(k)
    if not compared:
        card.verified, card.check_note = None, "screener.in has no figures for this quarter yet."
        return card
    names = ", ".join(k.upper() if len(k) <= 4 else k for k in compared)
    if off:
        card.verified = False
        card.check_note = (
            "Differs from screener.in on "
            + ", ".join(f"{k} ({a:,.0f} vs {b:,.0f})" for k, a, b in off)
            + "."
        )
    else:
        card.verified = True
        card.check_note = f"Matches screener.in on {names}, within 2%."
    if adjusted:
        card.check_note += (
            f" The filing shows a ₹{abs(assoc):,.1f} crore share of associates' {'profit' if assoc > 0 else 'loss'} "
            f"outside {', '.join(k.upper() for k in adjusted)}; screener.in counts it inside, and the check allows for that."
        )
    return card


# ---------------------------------------------------------------- entry point


def build(
    conn: sqlite3.Connection, llm: LLM | None, symbol: str, period_end: date
) -> ResultsCard | None:
    is_bank = bool(
        (
            conn.execute("SELECT is_bank FROM companies WHERE symbol = ?", (symbol,)).fetchone()
            or [0]
        )[0]
    )
    card = None
    try:
        card = from_xbrl(symbol, period_end)
    except Exception as exc:  # noqa: BLE001
        log.warning("XBRL rung failed for %s %s: %s", symbol, period_end, exc)
    if card is None and llm is not None and llm.configured:
        filing = conn.execute(
            f"SELECT f.* FROM {_RESULTS_FILINGS} AND f.symbol = ? AND f.filed_at > ? "
            "ORDER BY (f.text_quality = 'ok') DESC, f.n_pages DESC LIMIT 1",
            (symbol, period_end.isoformat()),
        ).fetchone()
        if filing:
            try:
                card = from_filing(conn, llm, filing, period_end)
            except (AIUnavailable, ValueError) as exc:
                log.warning("PDF rung failed for %s %s: %s", symbol, period_end, exc)
    if card is None:
        card = from_screener(conn, symbol, period_end, is_bank)
    if card is None:
        return None
    card = check(conn, card)
    conn.execute(
        "INSERT OR REPLACE INTO results_cards (symbol, period_end, basis, kind, card, source, verified, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (symbol, card.period_end, card.basis, card.kind, card.model_dump_json(), card.source,
         None if card.verified is None else int(card.verified), now_iso()),
    )  # fmt: skip
    conn.commit()
    return card


# Results filings by the AI's verdict when there is one, by the rules' otherwise. Eternal's
# results arrived as "Outcome of board meeting dated October 21", which only triage places.
_RESULTS_FILINGS = (
    "filings f LEFT JOIN filing_insights i ON i.filing_id = f.id "
    "WHERE COALESCE(i.category, f.category) = 'results' AND COALESCE(i.tier, f.tier) = 'must_see'"
)


def due(conn: sqlite3.Connection, days: int = 30) -> list[tuple[str, date]]:
    """(symbol, quarter) pairs with a results filing in the window."""
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        f"SELECT f.symbol, MIN(f.filed_at) AS first FROM {_RESULTS_FILINGS} AND f.filed_at >= ? GROUP BY f.symbol",
        (since,),
    ).fetchall()
    return [(r["symbol"], quarter_end_before(date.fromisoformat(r["first"][:10]))) for r in rows]


def load(conn: sqlite3.Connection, symbol: str, period_end: str) -> ResultsCard | None:
    row = conn.execute(
        "SELECT card FROM results_cards WHERE symbol = ? AND period_end = ?", (symbol, period_end)
    ).fetchone()
    return ResultsCard.model_validate(json.loads(row["card"])) if row else None
