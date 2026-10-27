"""Triage: the AI pass over filings the rules could not settle, or that need a summary.

Efficiency choices
- Only filings with needs_ai = 1 are sent. Routine paperwork never reaches a model.
- Filings go six to a call. One call with six short excerpts costs far less than six
  calls, and stays well inside the free tier's requests-per-minute limit.
- Each excerpt is the first 1,800 characters after stripping exchange letterheads
  ("To BSE Limited, Phiroze Jeejeebhoy Towers..."), which carry no information.
- The cheapest model does this work (Tier.LITE).

Judgement choices
- The model gets the company's annual revenue, so it can judge size: Polycab's
  ₹2.79 crore insolvency claim is tiny next to its revenue, so it should not sit at the
  top just because the word "insolvency" is in it.
- It may only use the filing and the facts given. It must say when the filing is unclear.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import date, timedelta

from pydantic import BaseModel, Field

from finn.ai.llm import GEMINI_ROUTES, LLM, AIUnavailable, Tier
from finn.config import BY_SYMBOL, DATA_DIR
from finn.contracts import PeopleCard
from finn.enrich import events, results
from finn.rules import CATEGORIES
from finn.store import now_iso, upsert
from finn.textclean import clean
from finn.units import to_crore

log = logging.getLogger(__name__)

# v2, after a hand review of the first 12 live answers: v1 wrote generic lines such as
# "quarterly results are critical for evaluating financial health", promoted a results
# presentation to must_see next to the results themselves, filed a loan guarantee under
# credit_rating, and rated a dividend's tax-deduction notice as worth a glance.
# v3: v2's why_it_matters lines were factual but mostly repeated the summary.
# v4: one filing can hold several events (Nazara's board outcome: share allotment, CFO
#     change, director resignation). The prompt now gets the events found in the text and
#     the people card's facts, and the answer lists every event. Copies of a letter
#     already triaged are skipped.
# v5: v4 turned Persistent's "INR 42,646.09 million" into "4,264.61 million (426.46
#     crore)", ten times too small. The model now copies amounts with their unit exactly
#     as printed, and code does the unit conversion.
# v6: v5 wrote that HDFC Bank's outgoing CEO "steered the bank through the ICICI merger",
#     joining the filing's unnamed merger to the new CEO's ICICI background. Added a rule
#     against attaching facts across people or events, and important filings now go to
#     the stronger model (see IMPORTANT).
# v7: v6 stored Adani Enterprises' "$50 billion" market forecast as a deal of ₹5,000
#     crore. The amount is now only the company's own transaction, with its currency, and
#     code converts only rupee amounts.
PROMPT_VERSION = "triage-v7"
BATCH = 6
EXCERPT_CHARS = 1800

SYSTEM = f"""You filter exchange filings for a professional investor who owns the stock.
For each filing decide how much attention it deserves, and say why in plain English.

Categories: {", ".join(CATEGORIES)}.
Category hints: call recordings, transcripts and call notices are earnings_call.
Guarantees, loans and credit facilities are fund_raise. A results presentation, results
press release or results newspaper notice is results.

Tiers:
- must_see: could change the view on the stock. The results statement itself; large
  deals; a new or departing CEO, CFO or MD; fund raising; litigation, regulatory action or
  penalties that are large relative to annual revenue; credit rating downgrades; promoter
  pledging or selling.
- glance: worth one line. Documents that accompany results (presentation, press release);
  smaller deals; director changes; order wins; rating upgrades or affirmations; dividends;
  monthly business updates.
- routine: compliance paperwork with no investment content, including procedural
  follow-ups to something already announced, such as tax-deduction notes on a dividend.

Rules:
- Use only the filing text and the facts given. Never use outside knowledge. Never invent
  numbers. If the excerpt does not say what happened, say so in the summary.
- Never attach a fact about one person, company or event to another. If the filing
  mentions something without naming it (for example "one of the largest mergers"), do
  not supply the name. Do not describe history the filing does not state.
- When "results numbers" are given, the summary must state the most important of them:
  which line moved most, and in which direction.
- When "leadership changes" are given, name the person, the role and where they came from.
- events: every kind of event the filing contains, from the categories list, most
  important first. category must equal the first event. Use "events found in the text"
  as hints, and drop any that the excerpt does not support.
- Judge size against annual revenue when an amount is stated, and say so.
- Write every amount exactly as the filing prints it, with its unit ("INR 42,646.09
  million", "Rs 2.79 crore"). Never convert between units, and never do arithmetic on
  amounts in title, summary or why_it_matters. The one exception is the given annual
  revenue comparison, which you may state only as given.
- title: at most 10 words, no company name. summary: one sentence, at most 30 words.
- why_it_matters: at most 25 words. It must add something the summary does not say: the
  comparison, cause, scale or consequence, backed by a specific fact given to you. For
  results, use the margin or the line that explains the profit move. If it would only
  repeat the summary, or would be a general statement about this kind of filing, use null.
- amount_value, amount_unit and amount_currency: the main amount of the company's own
  deal, fund raise, order, claim or penalty, exactly as printed: the number, its unit (one
  of rupees, thousand, lakh, million, crore, billion) and its currency (INR, USD, EUR...).
  Not market sizes, forecasts, revenue or per-share figures. Otherwise all null.
- Keep the given category unless it is clearly wrong."""


def strip_company(title: str, symbol: str) -> str:
    """The card already shows the company. The model sometimes repeats it despite the rule."""
    company = BY_SYMBOL.get(symbol)
    t = title.strip()
    for name in filter(None, (company.name if company else None, symbol)):
        for variant in (name, name.split()[0]):
            if len(variant) > 2 and t.lower().startswith(variant.lower()):
                rest = t[len(variant) :].lstrip(" :–-'s")
                if rest:
                    return rest[0].upper() + rest[1:]
    return t


RUPEE = {"INR", "RS", "RS.", "₹", "RUPEE", "RUPEES"}


def amount_crore(it: ItemOut) -> float | None:
    """Rupee amounts only: a dollar figure in crore would be wrong by the exchange rate."""
    if it.amount_currency and it.amount_currency.strip().upper() not in RUPEE:
        return None
    return to_crore(it.amount_value or None, it.amount_unit)


class ItemOut(BaseModel):
    id: str
    events: list[str] = Field(description="every event in the filing, most important first")
    category: str
    tier: str = Field(description="must_see, glance or routine")
    title: str
    summary: str
    why_it_matters: str | None
    sentiment: str = Field(description="positive, negative, neutral or mixed")
    amount_value: float | None = Field(None, description="the number as printed, e.g. 42646.09")
    amount_unit: str | None = Field(None, description="its unit as printed, e.g. million")
    amount_currency: str | None = Field(None, description="INR, USD, EUR... as printed")


class BatchOut(BaseModel):
    items: list[ItemOut]


_LETTERHEAD = re.compile(
    r"bse limited|national stock exchange|phiroze|jeejeebhoy|dalal street|bandra|exchange plaza|"
    r"scrip code|symbol\s*:|dear sir|dear madam|listing department|corporate relationship|"
    r"department of corporate services|^\s*(to|sub|ref)\s*[:.]",
    re.I,
)


def excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    lines = [ln.strip() for ln in clean(text).splitlines()]
    kept = [ln for ln in lines if ln and not _LETTERHEAD.search(ln)]
    return re.sub(r"\s+", " ", " ".join(kept))[:limit]


def annual_revenue(conn: sqlite3.Connection, symbol: str) -> float | None:
    rows = conn.execute(
        "SELECT period, value FROM financials WHERE symbol = ? AND statement = 'quarters' "
        "AND line_item IN ('Sales', 'Revenue') AND value IS NOT NULL ORDER BY period DESC LIMIT 4",
        (symbol,),
    ).fetchall()
    return round(sum(r["value"] for r in rows)) if len(rows) == 4 else None


def pending(conn: sqlite3.Connection, days: int) -> list[sqlite3.Row]:
    """Filings that need the AI, minus copies of a letter already in the queue or done.

    Companies often file one letter under several labels: Nazara's 12 October board
    outcome went out six times. The copies inherit the original's insight at export.

    An important filing answered by Flash-Lite got a stand-in while Flash was busy, so it
    is asked again until Flash answers.
    """
    since = (date.today() - timedelta(days=days)).isoformat()
    lite = GEMINI_ROUTES[Tier.LITE].model
    rows = conn.execute(
        "SELECT f.*, i.model AS answered_by, i.prompt_version AS answered_version "
        "FROM filings f LEFT JOIN filing_insights i ON i.filing_id = f.id "
        "LEFT JOIN filing_signals s ON s.filing_id = f.id "
        "WHERE f.needs_ai = 1 AND f.filed_at >= ? AND s.duplicate_of IS NULL "
        "AND (i.filing_id IS NULL OR i.prompt_version != ? OR i.model = ?) ORDER BY f.filed_at DESC",
        (since, PROMPT_VERSION, lite),
    ).fetchall()
    return [
        r
        for r in rows
        if r["answered_version"] != PROMPT_VERSION
        or r["answered_by"] != lite
        or is_important(conn, r)
    ]


def _events_line(conn: sqlite3.Connection, f: sqlite3.Row) -> str | None:
    found, _ = events.load(conn, f["id"])
    if not found:
        return None
    return "events found in the text: " + "; ".join(f'{k} ("{v}")' for k, v in found.items())


def _people_line(conn: sqlite3.Connection, f: sqlite3.Row) -> str | None:
    row = conn.execute("SELECT card FROM people_cards WHERE filing_id = ?", (f["id"],)).fetchone()
    if not row:
        return None
    parts = []
    for c in PeopleCard.model_validate_json(row["card"]).changes:
        bits = [f"{c.person}, {c.change}, {c.role}"]
        if c.effective_date:
            bits.append(f"effective {c.effective_date}")
        if c.previous_roles:
            bits.append("previously " + "; ".join(c.previous_roles[:3]))
        parts.append(", ".join(bits))
    return "leadership changes (from the filing's own profile section): " + " | ".join(parts)


def _item(conn: sqlite3.Connection, f: sqlite3.Row) -> str:
    company = BY_SYMBOL.get(f["symbol"])
    revenue = annual_revenue(conn, f["symbol"])
    body = ""
    if f["text_path"] and f["text_quality"] == "ok":
        body = excerpt((DATA_DIR / f["text_path"]).read_text(encoding="utf-8"))
    elif f["text_quality"] in ("garbled", "no_text"):
        body = "(The attachment is a scan with no reliable text. Judge from the subject and headline only.)"
    facts = [
        f"id: {f['id']}",
        f"company: {company.name if company else f['symbol']} ({company.sector if company else 'sector unknown'})",
        f"annual revenue: {'about ₹' + format(revenue, ',') + ' crore' if revenue else 'unknown'}",
        f"filed: {f['filed_at'][:16].replace('T', ' ')}",
        f"exchange subject: {f['exchange_label']}",
        f"headline: {f['headline']}",
        f"category from rules: {f['category'] or 'not decided'}",
    ]
    for line in (_events_line(conn, f), _results_numbers(conn, f), _people_line(conn, f)):
        if line:
            facts.append(line)
    facts.append(f"excerpt: {body or '(none)'}")
    return "\n".join(facts)


def _results_numbers(conn: sqlite3.Connection, f: sqlite3.Row) -> str | None:
    """The results card's figures, so a results summary can say what actually moved."""
    looks_like_results = (
        f["category"] == "results"
        or "results" in events.load(conn, f["id"])[0]
        or re.search(
            r"financial results|quarterly results|press release",
            f"{f['exchange_label']} {f['headline']}",
            re.I,
        )
    )
    if not looks_like_results:
        return None
    q = results.quarter_end_before(date.fromisoformat(f["filed_at"][:10]))
    card = results.load(conn, f["symbol"], q.isoformat())
    if not card:
        return None
    parts = []
    for m in card.metrics:
        if m.current is None:
            continue
        moves = [f"QoQ {m.qoq_pct:+.1f}%" if m.qoq_pct is not None else None,
                 f"YoY {m.yoy_pct:+.1f}%" if m.yoy_pct is not None else None]  # fmt: skip
        parts.append(f"{m.label} {m.current:,.1f} ({', '.join(x for x in moves if x)})")
    if card.margin_pct and card.margin_pct[0] is not None:
        parts.append(
            f"{card.margin_label} {card.margin_pct[0]}% (a quarter ago {card.margin_pct[1]}%, a year ago {card.margin_pct[2]}%)"
        )
    return (
        f"results numbers ({card.period_label}, {card.basis}, ₹ crore, from the company's XBRL filing): "
        + "; ".join(parts)
    )


# Filings an investor reads first go to the stronger model. On the live test the cheap
# model wrote that HDFC Bank's outgoing CEO "steered the bank through the ICICI merger":
# it fused the filing's unnamed merger with the incoming CEO's ICICI background. These
# events are about 40 filings a month, so the stronger model costs little where it matters.
IMPORTANT = {"results", "management_change", "M&A", "fund_raise", "litigation", "pledging"}


def is_important(conn: sqlite3.Connection, f: sqlite3.Row) -> bool:
    found, _ = events.load(conn, f["id"])
    return f["tier"] == "must_see" or bool(IMPORTANT & (set(found) | {f["category"]}))


def run(conn: sqlite3.Connection, llm: LLM, days: int = 30, limit: int | None = None) -> dict:
    todo = pending(conn, days)[:limit] if limit else pending(conn, days)
    stats = {
        "pending": len(todo),
        "done": 0,
        "batches": 0,
        "failed_batches": 0,
        "on_flash": 0,
        "on_lite": 0,
    }
    important = [f for f in todo if is_important(conn, f)]
    rest = [f for f in todo if not is_important(conn, f)]
    batches = [(Tier.FLASH, important[i : i + BATCH]) for i in range(0, len(important), BATCH)]
    batches += [(Tier.LITE, rest[i : i + BATCH]) for i in range(0, len(rest), BATCH)]
    for tier, batch in batches:
        prompt = "Filings:\n\n" + "\n\n".join(_item(conn, f) for f in batch)
        try:
            out = llm.json("triage", tier, prompt, BatchOut, system=SYSTEM, version=PROMPT_VERSION)
            stats["on_flash" if tier == Tier.FLASH else "on_lite"] += len(batch)
        except AIUnavailable as exc:
            log.warning("triage stopped: %s", exc)
            stats["failed_batches"] += 1
            break
        stats["batches"] += 1
        by_id = {f["id"]: f for f in batch}
        rows = []
        for it in out.items:
            if it.id not in by_id:
                continue
            rows.append(
                {
                    "filing_id": it.id,
                    "events": json.dumps(
                        [e for e in it.events if e in CATEGORIES] or [it.category]
                    ),
                    "category": it.category if it.category in CATEGORIES else None,
                    "tier": it.tier if it.tier in ("must_see", "glance", "routine") else None,
                    "title": strip_company(it.title, by_id[it.id]["symbol"]),
                    "summary": it.summary.strip(),
                    "why_it_matters": (it.why_it_matters or "").strip() or None,
                    "sentiment": it.sentiment
                    if it.sentiment in ("positive", "negative", "neutral", "mixed")
                    else "neutral",
                    "amount_inr_crore": amount_crore(it),
                    "model": llm.last_model,
                    "prompt_version": PROMPT_VERSION,
                    "created_at": now_iso(),
                }
            )
        upsert(conn, "filing_insights", rows, ("filing_id",))
        conn.commit()
        stats["done"] += len(rows)
    return stats
