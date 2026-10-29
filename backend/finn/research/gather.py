"""Collect one company's primary documents: the last four call transcripts and the latest
annual report, with screener.in's tables. Works for any NSE ticker screener.in covers.

screener.in links transcripts days to weeks late, and misses some: Infosys's October 2026
call was on NSE before screener.in listed it, and Maruti's July 2026 call never was. So
FINN also reads NSE's own announcements, a year back, and takes any call screener.in
lacks. It quietly does without if NSE does not answer.
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
from finn.store import now_iso

log = logging.getLogger(__name__)

FRESH_HOURS = 12
NSE_LOOKBACK_DAYS = 400  # four quarterly calls, and room for a late one
NSE_RECHECK = timedelta(hours=6)  # NSE throttles bursts; once per company is enough
RECENT_CALL_DAYS = 75  # a call this recent cannot have a newer one yet
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


def same_call(a: str, b: str) -> bool:
    """Two transcripts dated within a month are one call: screener.in dates a transcript by
    the call, NSE by its filing, up to five working days later."""
    return abs(_months_between(a, b)) < 2


def needs_nse_check(have: list[str], today: date) -> bool:
    """Whether a call FINN lacks can exist: fewer than four readable calls, or the newest
    old enough that a newer one may have happened.

    NSE is a bonus source here, and under a burst of requests it throttles; its retries
    then cost minutes. On 28 Oct a question asked alongside nine live research requests
    waited over 120 seconds for it.
    """
    if len(have) < TRANSCRIPTS_PER_COMPANY:
        return True
    y, m = (int(x) for x in max(have).split("-"))
    return (today - date(y, m, 15)).days > RECENT_CALL_DAYS


def calls_to_fetch(have: list[str], filed: list[str]) -> list[str]:
    """Of the transcript periods NSE lists, the ones to download: calls not already held,
    newest first, until the newest four calls are covered."""
    want = []
    for period in sorted(set(filed), reverse=True):
        known = have + want
        if (
            len(known) >= TRANSCRIPTS_PER_COMPANY
            and period < sorted(known)[-TRANSCRIPTS_PER_COMPANY]
        ):
            break
        if not any(same_call(period, k) for k in known):
            want.append(period)
    return want


def _readable(conn: sqlite3.Connection, symbol: str) -> list[sqlite3.Row]:
    """Readable transcripts, newest first, one per call."""
    out: list[sqlite3.Row] = []
    for r in conn.execute(
        "SELECT * FROM documents WHERE symbol = ? AND kind = 'transcript' AND text_path IS NOT NULL "
        "AND text_quality = 'ok' ORDER BY period DESC",
        (symbol,),
    ):
        if not any(same_call(r["period"], o["period"]) for o in out):
            out.append(r)
    return out


def _calls_from_nse(conn: sqlite3.Connection, company, force: bool = False) -> list[str]:
    """Download the calls screener.in has not listed. Returns their periods. force is for a
    rebuild asked for because a new transcript was seen, or by the reader."""
    have = [r["period"] for r in _readable(conn, company.symbol)]
    today = date.today()
    key = f"nse_transcripts_checked:{company.symbol}"
    last = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if not force and (
        not needs_nse_check(have, today)
        or (last and datetime.now(UTC) - datetime.fromisoformat(last[0]) < NSE_RECHECK)
    ):
        return []
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, now_iso()))
    conn.commit()
    try:
        items = filings.fetch_nse(company, today - timedelta(days=NSE_LOOKBACK_DAYS), today)
    except Exception as exc:  # noqa: BLE001 - NSE is a bonus source here, never a blocker
        log.info("NSE announcements unavailable for %s: %s", company.symbol, exc)
        return []
    by_period: dict[str, dict] = {}
    for x in sorted(items, key=lambda x: x["filed_at"], reverse=True):
        if "transcript" in f"{x['exchange_label']} {x['headline']}".lower() and x["attachment_url"]:
            by_period.setdefault(x["filed_at"][:7], x)
    added = []
    for period in calls_to_fetch(have, list(by_period)):
        x = by_period[period]
        doc = {"id": fundamentals._doc_id(x["attachment_url"]), "symbol": company.symbol,
               "kind": "transcript", "period": period, "title": f"Call transcript {period}",
               "url": x["attachment_url"], "source_url": x["source_url"]}  # fmt: skip
        try:
            if fundamentals.download_document(conn, doc).get("text_quality") == "ok":
                added.append(period)
        except Exception as exc:  # noqa: BLE001
            log.info("could not fetch NSE transcript %s: %s", x["attachment_url"], exc)
    return added


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


def gather(
    conn: sqlite3.Connection, symbol: str, refresh: bool = False, check_nse: bool = True
) -> Sources:
    company = fundamentals.company_for(symbol)
    notes, failed = [], []
    if refresh or not _is_fresh(conn, company.symbol):
        failed = fundamentals.run(conn, company)["failed"]  # "transcript 2026-01: <error>"
    added = _calls_from_nse(conn, company, force=refresh) if check_nse else []
    if added:
        notes.append(
            f"Transcripts for {', '.join(sorted(added))} taken from NSE; screener.in had not "
            "listed them."
        )
    held = [r["period"] for r in _readable(conn, company.symbol)]
    for f in failed:
        kind, _, rest = f.partition(" ")
        period = rest.split(":")[0]
        if kind == "transcript" and (
            any(same_call(period, p) for p in held)  # the same call came from NSE
            or (len(held) >= TRANSCRIPTS_PER_COMPANY and period < held[TRANSCRIPTS_PER_COMPANY - 1])
        ):
            continue  # or it is older than the four calls read
        notes.append(f"Could not read the {kind.replace('_', ' ')} for {period}.")

    row = conn.execute("SELECT * FROM companies WHERE symbol = ?", (company.symbol,)).fetchone()
    basis = conn.execute(
        "SELECT basis FROM financials WHERE symbol = ? GROUP BY basis "
        "ORDER BY basis = 'consolidated' DESC LIMIT 1",
        (company.symbol,),
    ).fetchone()
    src = Sources(
        symbol=company.symbol,
        name=row["name"] if row else company.name,
        sector=row["sector"] if row else None,
        basis=basis[0] if basis else "consolidated",
        is_bank=bool(row["is_bank"]) if row else False,
        notes=notes,
    )
    for r in _readable(conn, company.symbol)[:TRANSCRIPTS_PER_COMPANY]:
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
    if 0 < len(src.transcripts) < TRANSCRIPTS_PER_COMPANY:  # none at all is said by the engine
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
