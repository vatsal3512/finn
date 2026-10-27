"""Find every event a filing contains, by reading it, not by trusting its label.

A board-meeting outcome often bundles several decisions. Nazara's of 12 October 2026
covers a preferential share allotment, a whole-time director's resignation and a new CFO;
it was filed once as "Allotment of Securities" and once as "Outcome of Board Meeting".
A single category per filing would hide the CFO change from the people step.

So each readable filing is scanned with a few precise patterns, and every event found is
stored with the snippet that triggered it. Later steps use the events, not the label:
- people cards are built for any filing with a leadership change in it;
- results cards attach to any filing with a results statement in it;
- triage is told every event, and filings about the same event are grouped.

Copies of the same letter filed twice are spotted by a fingerprint of their text, so the
investor sees the event once.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import date, datetime, timedelta

from finn.config import DATA_DIR
from finn.textclean import clean

SCAN_CHARS = 15000

# Precise on purpose. "Company Secretary & Compliance Officer" under a signature must not
# count as a leadership change, so a change needs an action word near a role.
_ROLE = (
    r"(chief executive|chief financial|chief operating|managing director|whole[- ]?time director|"
    r"executive director|\bceo\b|\bcfo\b|\bcoo\b|key managerial|company secretary|"
    r"independent director|non[- ]executive director|chairman|chairperson)"
)
# Stay within one sentence, but let honorifics through: "the resignation of Mr. Rakesh Shah
# from the position of Chief Financial Officer" has a full stop inside "Mr.".
_SAME_SENTENCE = r"(?:[^.]|\b(?:Mr|Mrs|Ms|Dr|Shri|Smt|Prof|Sh)\.)"
PATTERNS = {
    "results": r"(unaudited|audited)\s.{0,80}financial results|financial results\s+(for|of)\s+the\s+(quarter|period|half)",
    "management_change": (
        r"(appoint(ed|ment)|re-?appoint|resign(ed|ation)?|cessation|ceases?|retire(s|d|ment)?|redesignat\w*)"
        + _SAME_SENTENCE
        + "{0,140}"
        + _ROLE
        + "|"
        + _ROLE
        + _SAME_SENTENCE
        + "{0,60}(appointed|resigned|re-?appointed|retires|ceased)"
    ),  # fmt: skip
    "dividend": r"(interim|final|special)\s+dividend\s+of|dividend\s+of\s*(rs\.?|₹|inr|~)\s*\d|declar\w+\s.{0,40}dividend",
    "fund_raise": (
        r"preferential\s+(issue|allotment|basis)|rights\s+issue|qualified\s+institution\w*\s+placement|"
        r"allot\w*\s.{0,80}(equity shares|warrants|debentures|ncds?)|buy-?back\s+of|credit\s+facilit"
    ),
    "M&A": (
        r"acquisition\s+of|to\s+acquire|amalgamation|scheme\s+of\s+(arrangement|amalgamation)|demerger|"
        r"joint\s+venture\s+agreement|slump\s+sale|divest\w*|binding\s+term\s+sheet"
    ),
    # Not bare "insolvency": every appointment annexe declares the person is not debarred
    # under insolvency law, which is boilerplate, not a dispute.
    "litigation": (
        r"corporate\s+insolvency|insolvency\s+(resolution|proceedings|petition|application)|show[- ]cause|"
        r"penalty\s+of|order\s+(passed|dated)\s.{0,60}(tribunal|court|sebi|nclt|nclat)|\bnclat\b|\bnclt\b"
    ),
    "credit_rating": r"credit\s+rating|rating\s+(upgrade|downgrade|reaffirm)",
    "pledging": r"\bpledg|encumbrance",
}
_COMPILED = {k: re.compile(v, re.I) for k, v in PATTERNS.items()}

# Most important first: the lead event names a filing's group.
PRIORITY = ("results", "management_change", "M&A", "fund_raise", "litigation", "pledging",
            "credit_rating", "dividend")  # fmt: skip


# A results mention that only announces a future meeting: "to consider and approve the
# unaudited financial results" (Asian Paints, 6 October) is a notice, not the results.
# Future intent only: "considered and approved the results" (Eternal) is a decision.
_FUTURE = re.compile(
    r"\bto consider\b|to be held|will be held|scheduled|intimation of|\bpropos|for declaration of",
    re.I,
)
# A letter announcing a future board meeting that never says anything was approved.
_NOTICE = re.compile(
    r"will be held|is scheduled to be held|to consider(,| and approve)? the following", re.I
)
_DECIDED = re.compile(r"\bapproved\b|at (its|their) meeting held (today|on)", re.I)


def detect(text: str, label: str = "", headline: str = "") -> dict[str, str]:
    """event -> the snippet that triggered it."""
    body = f"{label}\n{headline}\n{clean(text[:SCAN_CHARS])}"
    head = body[:3000]
    only_a_notice = bool(_NOTICE.search(head)) and not _DECIDED.search(
        head.replace("Approval of", "")
    )
    found = {}
    for event, rx in _COMPILED.items():
        for m in rx.finditer(body):
            if event == "results" and (
                only_a_notice or _FUTURE.search(body[max(0, m.start() - 160) : m.start()])
            ):
                continue
            found[event] = " ".join(m.group(0).split())[:160]
            break
    return found


def fingerprint(text: str) -> str:
    """Same letter, same fingerprint, whatever the cover page or spacing."""
    words = re.findall(r"[a-z0-9]+", clean(text).lower())
    start = 60 if len(words) > 300 else 0  # skip cover-letter wording only when there is a body
    return hashlib.sha1(" ".join(words[start : start + 400]).encode()).hexdigest()[:16]


def lead_event(events: list[str] | dict, category: str | None) -> str | None:
    present = set(events) | ({category} if category else set())
    for e in PRIORITY:
        if e in present:
            return e
    return category


def run(conn: sqlite3.Connection, days: int = 30) -> dict:
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT f.id, f.symbol, f.filed_at, f.exchange_label, f.headline, f.text_path FROM filings f "
        "LEFT JOIN filing_signals s ON s.filing_id = f.id "
        "WHERE f.filed_at >= ? AND f.text_quality = 'ok' AND f.text_path IS NOT NULL AND s.filing_id IS NULL "
        "ORDER BY f.filed_at",
        (since,),
    ).fetchall()
    stats = {"scanned": 0, "with_several_events": 0, "duplicates": 0}
    for r in rows:
        text = (DATA_DIR / r["text_path"]).read_text(encoding="utf-8")
        events = detect(text, r["exchange_label"] or "", r["headline"] or "")
        fp = fingerprint(text)
        when = datetime.fromisoformat(r["filed_at"])
        twin = conn.execute(
            "SELECT s.filing_id FROM filing_signals s JOIN filings f ON f.id = s.filing_id "
            "WHERE f.symbol = ? AND s.fingerprint = ? AND f.filed_at BETWEEN ? AND ? AND s.filing_id != ? "
            "ORDER BY f.filed_at LIMIT 1",
            (r["symbol"], fp, (when - timedelta(days=2)).isoformat(), r["filed_at"], r["id"]),
        ).fetchone()
        conn.execute(
            "INSERT OR REPLACE INTO filing_signals (filing_id, events, fingerprint, duplicate_of) VALUES (?, ?, ?, ?)",
            (r["id"], json.dumps(events), fp, twin["filing_id"] if twin else None),
        )
        stats["scanned"] += 1
        stats["with_several_events"] += len(events) > 1
        stats["duplicates"] += twin is not None
    conn.commit()
    return stats


def load(conn: sqlite3.Connection, filing_id: str) -> tuple[dict[str, str], str | None]:
    row = conn.execute(
        "SELECT events, duplicate_of FROM filing_signals WHERE filing_id = ?", (filing_id,)
    ).fetchone()
    return (json.loads(row["events"]), row["duplicate_of"]) if row else ({}, None)
