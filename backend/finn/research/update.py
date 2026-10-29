"""Keep the shipped research reports current, without anyone asking.

Each refresh compares what a report was built from with what the company has filed since.
A new call transcript, or new results, means the report is behind:

    detect    code, from the filings Push already collects (NSE for the research picks)
    rebuild   the full engine; each call's reading is cached, so only new calls cost a model
    promote   only a complete report, reading at least as many calls, replaces the old one

A report that is behind but not yet rebuilt says so in the app, so nobody mistakes it for
current. A rebuild that changed nothing is not retried for a day, so nothing loops.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from finn.collectors import filings
from finn.config import BY_SYMBOL, DATA_DIR, PORTFOLIO
from finn.contracts import ResearchReport
from finn.research.engine import research
from finn.store import now_iso

log = logging.getLogger(__name__)

REBUILDS_PER_RUN = 2  # a rebuild takes a minute or two; the refresh runs every 30 minutes
SAME_CALL_DAYS = 15  # a transcript is filed within five working days of its call
RESULTS_SETTLE = timedelta(days=1)  # screener.in's tables catch up with results within a day
LOOKBACK_DAYS = 60
STALE_CALL = timedelta(
    days=100
)  # a quarter and more since the newest call: a newer one should exist
NSE_MAX_DAYS = 400
# The same filing is not rebuilt for again until this has passed, whatever came of it.
RETRY_AFTER = {
    "updated": timedelta(days=1),
    "unchanged": timedelta(days=1),
    "failed": timedelta(hours=2),
}
NSE_EVERY = timedelta(hours=6)
INCOMPLETE = ("reasoning model was unavailable", "could not be read", "ran out of time")
OPEN = ("pending", "on_track", "at_risk", "unclear")
HOLDINGS = {c.symbol for c in PORTFOLIO}
_RESULTS = re.compile(r"financial results?\b", re.I)
_NOT_YET = re.compile(r"intimation|to consider|will be held|is scheduled|trading window", re.I)


@dataclass
class Filed:
    id: str
    filed_at: str
    text: str
    category: str | None = None


def newest_call(r: ResearchReport) -> date | None:
    """The date of the newest call a report read, from its label: "Q2 FY27 call, 21 Oct 2026"."""
    for d in r.documents:
        if d.kind != "transcript":
            continue
        if m := re.search(r"(\d{1,2} \w{3} \d{4})", d.label):
            return datetime.strptime(m.group(1), "%d %b %Y").date()
        if m := re.search(r"(\w{3} \d{4})", d.label):
            return datetime.strptime(f"15 {m.group(1)}", "%d %b %Y").date()
    return None


def reason(r: ResearchReport, filed: list[Filed], now: datetime) -> tuple[str, str] | None:
    """Why a report is behind, as (key, sentence), or None. The key names the filing, so a
    rebuild is not repeated for the same one."""
    called = newest_call(r)
    built = datetime.fromisoformat(r.generated_at)
    for f in sorted(filed, key=lambda f: f.filed_at, reverse=True):
        at = datetime.fromisoformat(f.filed_at)
        day = f"{at.day} {at:%b %Y}"
        if "transcript" in f.text.lower() and (
            called is None or at.date() > called + timedelta(days=SAME_CALL_DAYS)
        ):
            return f"transcript:{f.id}", f"A new call transcript was filed on {day}."
        is_results = f.category == "results" or (
            f.category is None and _RESULTS.search(f.text) and not _NOT_YET.search(f.text)
        )
        if is_results and at > built and now - at > RESULTS_SETTLE:
            return f"results:{f.id}", f"New results were filed on {day}."
    return None


def changes(old: ResearchReport, new: ResearchReport) -> list[str]:
    """What a rebuild changed, in a few words each, for the line above the report."""
    out = []
    first = lambda r: next((d.label for d in r.documents if d.kind == "transcript"), None)  # noqa: E731
    if first(new) and first(new) != first(old):
        out.append(f"Now reads the {first(new)}.")
    before = {(p.metric, p.period): p.verdict for p in old.promises}
    graded = [
        p
        for p in new.promises
        if before.get((p.metric, p.period)) in OPEN and p.verdict not in OPEN
    ]
    if graded:
        out.append(f"{len(graded)} promise{'s' if len(graded) > 1 else ''} newly graded: "
                   + ", ".join(f"{p.metric} {p.verdict.replace('_', ' ')}" for p in graded[:3]) + ".")  # fmt: skip
    added = sum((p.metric, p.period) not in before for p in new.promises)
    if added:
        out.append(f"{added} new promise{'s' if added > 1 else ''} from the latest calls.")
    return out


def complete(old: ResearchReport, new: ResearchReport) -> bool:
    if any(m in n for n in new.notes for m in INCOMPLETE):
        return False
    return new.stats.calls_read >= old.stats.calls_read and (bool(new.promises) or not old.promises)


def _filed(conn: sqlite3.Connection, r: ResearchReport) -> list[Filed] | None:
    """Recent filings: Push's own for a holding; NSE's for a research pick, or for a report
    whose newest call is so old that a newer one should exist (screener.in missed Maruti's
    July 2026 call). NSE is asked at most every six hours; None means not asked this time."""
    today = date.today()
    called = newest_call(r)
    out: list[Filed] = []
    if r.symbol in HOLDINGS:
        rows = conn.execute(
            "SELECT id, filed_at, exchange_label, headline, attachment_url, category FROM filings "
            "WHERE symbol = ? AND filed_at >= ?",
            (r.symbol, (today - timedelta(days=LOOKBACK_DAYS)).isoformat()),
        )
        out = [Filed(x["id"], x["filed_at"], f"{x['exchange_label']} {x['headline']} {x['attachment_url']}",
                     x["category"] or "") for x in rows]  # fmt: skip
        if called and today - called < STALE_CALL:
            return out
    key = f"update_nse_checked:{r.symbol}"
    last = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if last and datetime.now(UTC) - datetime.fromisoformat(last[0]) < NSE_EVERY:
        return out if r.symbol in HOLDINGS else None
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, now_iso()))
    conn.commit()
    since = max(
        today - timedelta(days=NSE_MAX_DAYS),
        min(called or today, today - timedelta(days=LOOKBACK_DAYS)),
    )
    try:
        items = filings.fetch_nse(BY_SYMBOL[r.symbol], since, today)
    except Exception as exc:  # noqa: BLE001 - try again on a later run
        log.info("NSE unavailable for %s: %s", r.symbol, exc)
        return out if r.symbol in HOLDINGS else None
    return out + [Filed(x["id"], x["filed_at"], f"{x['exchange_label']} {x['headline']} {x['attachment_url']}")
                  for x in items]  # fmt: skip


def _attempted(conn: sqlite3.Connection, symbol: str, key: str, now: datetime) -> bool:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (f"update:{symbol}",)).fetchone()
    if not row:
        return False
    last_key, outcome, at = row[0].split("|")
    return last_key == key and now - datetime.fromisoformat(at) < RETRY_AFTER[outcome]


def _record(conn: sqlite3.Connection, symbol: str, key: str, outcome: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                 (f"update:{symbol}", f"{key}|{outcome}|{now_iso()}"))  # fmt: skip
    conn.commit()


def run(conn: sqlite3.Connection, out: Path, limit: int = REBUILDS_PER_RUN) -> dict:
    """Rebuild up to `limit` reports that are behind; mark the rest as behind."""
    now = datetime.now(UTC)
    scratch = DATA_DIR / "research-rebuild"
    stats = {"behind": [], "updated": [], "unchanged": [], "failed": []}
    for path in sorted(out.glob("*.json")):
        if path.name == "index.json":
            continue
        old = ResearchReport.model_validate_json(path.read_text(encoding="utf-8"))
        filed = _filed(conn, old)
        why = reason(old, filed, now) if filed is not None else None
        if not why:
            continue
        key, sentence = why
        stats["behind"].append(old.symbol)
        if len(stats["updated"]) + len(stats["unchanged"]) + len(stats["failed"]) >= limit \
                or _attempted(conn, old.symbol, key, now):  # fmt: skip
            if old.pending != sentence:
                path.write_text(old.model_copy(update={"pending": sentence}).model_dump_json(indent=1),
                                encoding="utf-8")  # fmt: skip
            continue
        log.info("%s is behind: %s Rebuilding.", old.symbol, sentence)
        try:
            new = research(old.symbol, refresh=True, save_dir=scratch)
        except Exception as exc:  # noqa: BLE001 - keep the old report, retry later
            log.warning("rebuild failed for %s: %s", old.symbol, exc)
            new = None
        if new is None or not complete(old, new):
            _record(conn, old.symbol, key, "failed")
            stats["failed"].append(old.symbol)
            path.write_text(old.model_copy(update={"pending": sentence}).model_dump_json(indent=1),
                            encoding="utf-8")  # fmt: skip
            continue
        diff = changes(old, new)
        outcome = "updated" if diff else "unchanged"
        _record(conn, old.symbol, key, outcome)
        stats[outcome].append(old.symbol)
        path.write_text(new.model_copy(update={"changes": diff, "pending": None}).model_dump_json(indent=1),
                        encoding="utf-8")  # fmt: skip
    return stats
