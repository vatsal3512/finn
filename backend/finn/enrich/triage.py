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

import logging
import re
import sqlite3
from datetime import date, timedelta

from pydantic import BaseModel, Field

from finn.ai.llm import LLM, AIUnavailable, Tier
from finn.config import BY_SYMBOL, DATA_DIR
from finn.enrich import results
from finn.rules import CATEGORIES
from finn.store import now_iso, upsert

log = logging.getLogger(__name__)

# v2, after a hand review of the first 12 live answers: v1 wrote generic lines such as
# "quarterly results are critical for evaluating financial health", promoted a results
# presentation to must_see next to the results themselves, filed a loan guarantee under
# credit_rating, and rated a dividend's tax-deduction notice as worth a glance.
# v3: v2's why_it_matters lines were factual but mostly repeated the summary.
PROMPT_VERSION = "triage-v3"
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
- When "results numbers" are given, the summary must state the most important of them:
  which line moved most, and in which direction.
- Judge size against annual revenue when an amount is stated, and say so.
- title: at most 10 words, no company name. summary: one sentence, at most 30 words.
- why_it_matters: at most 25 words. It must add something the summary does not say: the
  comparison, cause, scale or consequence, backed by a specific fact given to you. For
  results, use the margin or the line that explains the profit move. If it would only
  repeat the summary, or would be a general statement about this kind of filing, use null.
- amount_inr_crore: the main rupee amount in crore if the filing states one, else null.
- Keep the given category unless it is clearly wrong."""


class ItemOut(BaseModel):
    id: str
    category: str
    tier: str = Field(description="must_see, glance or routine")
    title: str
    summary: str
    why_it_matters: str | None
    sentiment: str = Field(description="positive, negative, neutral or mixed")
    amount_inr_crore: float | None


class BatchOut(BaseModel):
    items: list[ItemOut]


_LETTERHEAD = re.compile(
    r"bse limited|national stock exchange|phiroze|jeejeebhoy|dalal street|bandra|exchange plaza|"
    r"scrip code|symbol\s*:|dear sir|dear madam|listing department|corporate relationship|"
    r"department of corporate services|^\s*(to|sub|ref)\s*[:.]",
    re.I,
)


def excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    lines = [ln.strip() for ln in text.splitlines()]
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
    since = (date.today() - timedelta(days=days)).isoformat()
    return conn.execute(
        "SELECT f.* FROM filings f LEFT JOIN filing_insights i ON i.filing_id = f.id "
        "WHERE f.needs_ai = 1 AND f.filed_at >= ? AND (i.filing_id IS NULL OR i.prompt_version != ?) "
        "ORDER BY f.filed_at DESC",
        (since, PROMPT_VERSION),
    ).fetchall()


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
    numbers = _results_numbers(conn, f)
    if numbers:
        facts.append(numbers)
    facts.append(f"excerpt: {body or '(none)'}")
    return "\n".join(facts)


def _results_numbers(conn: sqlite3.Connection, f: sqlite3.Row) -> str | None:
    """The results card's figures, so a results summary can say what actually moved."""
    looks_like_results = f["category"] == "results" or re.search(
        r"financial results|quarterly results|press release",
        f"{f['exchange_label']} {f['headline']}",
        re.I,
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


def run(conn: sqlite3.Connection, llm: LLM, days: int = 30, limit: int | None = None) -> dict:
    todo = pending(conn, days)[:limit] if limit else pending(conn, days)
    stats = {"pending": len(todo), "done": 0, "batches": 0, "failed_batches": 0}
    for i in range(0, len(todo), BATCH):
        batch = todo[i : i + BATCH]
        prompt = "Filings:\n\n" + "\n\n".join(_item(conn, f) for f in batch)
        try:
            out = llm.json(
                "triage", Tier.LITE, prompt, BatchOut, system=SYSTEM, version=PROMPT_VERSION
            )
        except AIUnavailable as exc:
            log.warning("triage stopped: %s", exc)
            stats["failed_batches"] += 1
            break
        stats["batches"] += 1
        ids = {f["id"] for f in batch}
        rows = []
        for it in out.items:
            if it.id not in ids:
                continue
            rows.append(
                {
                    "filing_id": it.id,
                    "category": it.category if it.category in CATEGORIES else None,
                    "tier": it.tier if it.tier in ("must_see", "glance", "routine") else None,
                    "title": it.title.strip(),
                    "summary": it.summary.strip(),
                    "why_it_matters": (it.why_it_matters or "").strip() or None,
                    "sentiment": it.sentiment
                    if it.sentiment in ("positive", "negative", "neutral", "mixed")
                    else "neutral",
                    "amount_inr_crore": it.amount_inr_crore,
                    "model": "gemini/groq",
                    "prompt_version": PROMPT_VERSION,
                    "created_at": now_iso(),
                }
            )
        upsert(conn, "filing_insights", rows, ("filing_id",))
        conn.commit()
        stats["done"] += len(rows)
    return stats
