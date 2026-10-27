"""Collect one company's primary documents: the last four call transcripts and the latest
annual report, with screener.in's tables. Works for any NSE ticker screener.in covers.

screener.in links transcripts days to weeks late: Infosys's October 2026 call was on NSE
before screener.in listed it. So FINN also checks NSE's own announcements for a newer
transcript, and quietly does without if NSE does not answer.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from finn.collectors import filings, fundamentals
from finn.config import DATA_DIR, TRANSCRIPTS_PER_COMPANY
from finn.pdftext import load_pages
from finn.research.quotes import Document

log = logging.getLogger(__name__)

FRESH_HOURS = 12
NSE_LOOKBACK_DAYS = 75
AR_PAGES_PER_SECTION = 3


@dataclass
class Sources:
    symbol: str
    name: str
    sector: str | None
    basis: str
    is_bank: bool
    transcripts: list[tuple[Document, str]] = field(default_factory=list)  # newest first
    annual_report: Document | None = None
    ar_period: str | None = None
    ar_sections: dict[str, list[int]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _months_between(a: str, b: str) -> int:
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def _newer_transcript_from_nse(conn: sqlite3.Connection, company) -> str | None:
    latest = conn.execute(
        "SELECT MAX(period) FROM documents WHERE symbol = ? AND kind = 'transcript'",
        (company.symbol,),
    ).fetchone()[0]
    try:
        items = filings.fetch_nse(
            company, date.today() - timedelta(days=NSE_LOOKBACK_DAYS), date.today()
        )
    except Exception as exc:  # noqa: BLE001 - NSE is a bonus source here, never a blocker
        log.info("NSE announcements unavailable for %s: %s", company.symbol, exc)
        return None
    for x in sorted(items, key=lambda x: x["filed_at"], reverse=True):
        text = f"{x['exchange_label']} {x['headline']}".lower()
        period = x["filed_at"][:7]
        # A transcript filed within a month of screener.in's latest is the same call.
        if "transcript" not in text or not x["attachment_url"]:
            continue
        if latest and _months_between(latest, period) < 2:
            continue
        doc = {"id": fundamentals._doc_id(x["attachment_url"]), "symbol": company.symbol,
               "kind": "transcript", "period": period, "title": f"Call transcript {period}",
               "url": x["attachment_url"], "source_url": x["source_url"]}  # fmt: skip
        try:
            fundamentals.download_document(conn, doc)
            return period
        except Exception as exc:  # noqa: BLE001
            log.info("could not fetch NSE transcript %s: %s", x["attachment_url"], exc)
    return None


def _is_fresh(conn: sqlite3.Connection, symbol: str) -> bool:
    row = conn.execute("SELECT updated_at FROM companies WHERE symbol = ?", (symbol,)).fetchone()
    have = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE symbol = ? AND kind = 'transcript' AND text_path IS NOT NULL",
        (symbol,),
    ).fetchone()[0]
    if not row or not row[0] or have == 0:
        return False
    age = datetime.now(UTC) - datetime.fromisoformat(row[0])
    return age < timedelta(hours=FRESH_HOURS)


def gather(conn: sqlite3.Connection, symbol: str, refresh: bool = False) -> Sources:
    company = fundamentals.company_for(symbol)
    notes = []
    if refresh or not _is_fresh(conn, company.symbol):
        stats = fundamentals.run(conn, company)
        notes += [f"Could not fetch {f}" for f in stats["failed"]]
    newer = _newer_transcript_from_nse(conn, company)
    if newer:
        notes.append(
            f"Newest transcript ({newer}) taken from NSE; screener.in had not listed it yet."
        )

    row = conn.execute("SELECT * FROM companies WHERE symbol = ?", (company.symbol,)).fetchone()
    basis = conn.execute(
        "SELECT basis FROM financials WHERE symbol = ? LIMIT 1", (company.symbol,)
    ).fetchone()
    src = Sources(
        symbol=company.symbol,
        name=row["name"] if row else company.name,
        sector=row["sector"] if row else None,
        basis=basis[0] if basis else "consolidated",
        is_bank=bool(row["is_bank"]) if row else False,
        notes=notes,
    )
    for r in conn.execute(
        "SELECT * FROM documents WHERE symbol = ? AND kind = 'transcript' AND text_path IS NOT NULL "
        "AND text_quality = 'ok' ORDER BY period DESC LIMIT ?",
        (company.symbol, TRANSCRIPTS_PER_COMPANY),
    ):
        pages = load_pages(DATA_DIR / r["text_path"])
        src.transcripts.append((Document(f"Call, {r['period']}", r["url"], pages), r["period"]))
    ar = conn.execute(
        "SELECT * FROM documents WHERE symbol = ? AND kind = 'annual_report' AND text_path IS NOT NULL "
        "AND text_quality = 'ok' ORDER BY period DESC LIMIT 1",
        (company.symbol,),
    ).fetchone()
    if ar:
        src.annual_report = Document(
            f"Annual report {ar['period']}", ar["url"], load_pages(DATA_DIR / ar["text_path"])
        )
        src.ar_period = ar["period"]
        src.ar_sections = json.loads(ar["sections"] or "{}")
    else:
        src.notes.append(
            "No readable annual report: the bear case uses the calls and accounts only."
        )
    if len(src.transcripts) < TRANSCRIPTS_PER_COMPANY:
        src.notes.append(f"Only {len(src.transcripts)} readable call transcripts were available.")
    return src


def ar_excerpts(src: Sources) -> list[tuple[str, int, str]]:
    """(section, page, text) for the first pages of each located annual-report section."""
    if not src.annual_report:
        return []
    out, used = [], set()
    for section, pages in src.ar_sections.items():
        for p in pages[:AR_PAGES_PER_SECTION]:
            if p in used or not 1 <= p <= len(src.annual_report.pages):
                continue
            used.add(p)
            out.append((section, p, src.annual_report.pages[p - 1].strip()))
    return out
