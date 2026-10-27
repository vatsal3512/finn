"""People cards: who is joining or leaving, with a bio from the filing itself (decision D4).

SEBI requires a "brief profile" whenever a director or key officer is appointed. That
profile is the company's own statement: more accurate than a web search, free, and
immune to mixing up two people with the same name.

Follow-up filings ("has assumed charge") often omit the profile. When an appointment has
no profile, FINN looks back 120 days for an earlier filing from the same company that
names the person, and takes the profile from there.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import date, timedelta

from pydantic import BaseModel

from finn.ai.llm import LLM, AIUnavailable, Tier
from finn.config import DATA_DIR
from finn.contracts import PeopleCard, PersonChange
from finn.enrich import events
from finn.store import now_iso
from finn.textclean import clean

log = logging.getLogger(__name__)

# v2, after a hand review: v1 read only the first profile section, so Nazara's new CFO,
# whose profile sits in an annexure 20,000 characters into the letter, was missed; and
# term renewals were reported as new appointments.
PROMPT_VERSION = "people-v2"
LOOKBACK_DAYS = 120
EXCERPT_BUDGET = 12000

SYSTEM = """You extract leadership changes from Indian exchange filings.
List each person who is appointed, reappointed, resigns, retires, ceases or is redesignated.
- Use only the text given. Never use outside knowledge about the person.
- profile: at most 45 words, from the filing's own profile or background section, or
  null if the filing has none. Keep concrete facts: past employers, roles, years.
- previous_roles: up to 5, as "Role, Organisation".
- change must be one of: appointment, reappointment, resignation, retirement, cessation,
  redesignation, other. Renewing the term of someone already in the role is reappointment.
- effective_date as YYYY-MM-DD if stated.
- The text may be several excerpts from one letter, separated by "...". Cover all of them."""


class Extract(BaseModel):
    changes: list[PersonChange]


_ANCHORS = re.compile(
    r"brief profile|profile of|background of|" + events.PATTERNS["management_change"], re.I
)


def _excerpt(text: str, budget: int = EXCERPT_BUDGET) -> str:
    """The announcement, plus a window around every leadership mention and profile.

    One board outcome can hold several people in several annexures, so a single window
    around the first "brief profile" is not enough.
    """
    text = clean(text)
    if len(text) <= budget:
        return text
    spans = [(0, 2500)] + [
        (max(0, m.start() - 400), m.start() + 1800) for m in _ANCHORS.finditer(text)
    ]
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    out, used = [], 0
    for start, end in merged:
        piece = text[start:end]
        if used + len(piece) > budget:
            piece = piece[: budget - used]
        out.append(piece)
        used += len(piece)
        if used >= budget:
            break
    return "\n...\n".join(out)


def _extract(llm: LLM, text: str) -> Extract:
    return llm.json(
        "people", Tier.LITE, _excerpt(text), Extract, system=SYSTEM, version=PROMPT_VERSION
    )


def _earlier_profile(
    conn: sqlite3.Connection, llm: LLM, filing: sqlite3.Row, person: str
) -> tuple[str | None, list[str], str | None]:
    surname = person.split()[-1]
    since = (
        date.fromisoformat(filing["filed_at"][:10]) - timedelta(days=LOOKBACK_DAYS)
    ).isoformat()
    rows = conn.execute(
        "SELECT id, text_path FROM filings WHERE symbol = ? AND id != ? AND filed_at >= ? AND filed_at <= ? "
        "AND text_path IS NOT NULL AND text_quality = 'ok' ORDER BY filed_at DESC",
        (filing["symbol"], filing["id"], since, filing["filed_at"]),
    ).fetchall()
    for r in rows:
        text = (DATA_DIR / r["text_path"]).read_text(encoding="utf-8")
        if surname.lower() not in text.lower() or not re.search(
            r"profile|experience|background", text, re.I
        ):
            continue
        for c in _extract(llm, text).changes:
            if surname.lower() in c.person.lower() and c.profile:
                return c.profile, c.previous_roles, r["id"]
    return None, [], None


def pending(conn: sqlite3.Connection, days: int) -> list[sqlite3.Row]:
    """Filings with a leadership change in them, by content or by category.

    By content matters: Nazara's 12 October CFO change sat inside a board outcome that
    was also filed as "Allotment of Securities". Copies of a letter already seen are
    skipped (filing_signals.duplicate_of).
    """
    since = (date.today() - timedelta(days=days)).isoformat()
    return conn.execute(
        "SELECT f.* FROM filings f LEFT JOIN filing_insights i ON i.filing_id = f.id "
        "LEFT JOIN people_cards p ON p.filing_id = f.id "
        "LEFT JOIN filing_signals s ON s.filing_id = f.id "
        "WHERE (COALESCE(i.category, f.category) = 'management_change' OR s.events LIKE '%\"management_change\"%') "
        "AND s.duplicate_of IS NULL AND f.filed_at >= ? AND f.text_path IS NOT NULL "
        "AND f.text_quality = 'ok' AND p.filing_id IS NULL ORDER BY f.filed_at",
        (since,),
    ).fetchall()


def _person_key(name: str) -> str:
    """'Mr. Anup Bagchi' and 'Anup  Bagchi' are the same person."""
    words = [
        w
        for w in re.findall(r"[a-z]+", name.lower())
        if w not in {"mr", "mrs", "ms", "dr", "shri", "smt"}
    ]
    return " ".join(words)


# Letter shapes OCR confuses. "Rohit Shanna" in Nazara's scanned letter of 13 October is
# "Rohit Sharma". A similarity score is the wrong tool: "Rohit Sharma" and "Mohit
# Sharma" score 0.92, as do "Rakesh Shah" and "Ramesh Shah", and they are different people.
# So OCR slips are undone first, and then names must match exactly.
_OCR = (
    ("rn", "m"),
    ("rm", "m"),
    ("nn", "m"),
    ("cl", "d"),
    ("vv", "w"),
    ("1", "i"),
    ("l", "i"),
    ("0", "o"),
)


def _canonical(name: str) -> str:
    words = [w for w in _person_key(name).split() if len(w) > 1]  # drop initials: Atul B. Lall
    out = "".join(words)  # OCR also splits words: "Roh it Shanna"
    for wrong, right in _OCR:
        out = out.replace(wrong, right)
    return out


def same_person(a: str, b: str) -> bool:
    return _canonical(a) == _canonical(b)


def _already_carded(change, seen: list[tuple[str, str]]) -> bool:
    return any(change.change == ch and same_person(change.person, person) for person, ch in seen)


def _seen_recently(
    conn: sqlite3.Connection, filing: sqlite3.Row, window_days: int = 3
) -> list[tuple[str, str]]:
    """(person, change) pairs already on a card for this company within a few days."""
    day = date.fromisoformat(filing["filed_at"][:10])
    rows = conn.execute(
        "SELECT p.card FROM people_cards p JOIN filings f ON f.id = p.filing_id "
        "WHERE p.symbol = ? AND f.filed_at BETWEEN ? AND ?",
        (
            filing["symbol"],
            (day - timedelta(days=window_days)).isoformat(),
            (day + timedelta(days=window_days + 1)).isoformat(),
        ),
    ).fetchall()
    return [
        (c.person, c.change)
        for r in rows
        for c in PeopleCard.model_validate_json(r["card"]).changes
    ]


def run(conn: sqlite3.Connection, llm: LLM, days: int = 30) -> dict:
    todo = pending(conn, days)
    stats = {
        "pending": len(todo),
        "cards": 0,
        "profiles_from_earlier_filings": 0,
        "duplicate_changes_dropped": 0,
    }
    for f in todo:
        try:
            ext = _extract(llm, (DATA_DIR / f["text_path"]).read_text(encoding="utf-8"))
            seen = _seen_recently(conn, f)
            fresh = [c for c in ext.changes if not _already_carded(c, seen)]
            stats["duplicate_changes_dropped"] += len(ext.changes) - len(fresh)
            ext.changes = fresh
            for c in ext.changes:
                if c.change == "appointment" and not c.profile:
                    c.profile, roles, src = _earlier_profile(conn, llm, f, c.person)
                    if src:
                        c.previous_roles = c.previous_roles or roles
                        c.profile_source = src
                        stats["profiles_from_earlier_filings"] += 1
        except AIUnavailable as exc:
            log.warning("people cards stopped: %s", exc)
            break
        if not ext.changes:
            continue
        card = PeopleCard(changes=ext.changes)
        conn.execute(
            "INSERT OR REPLACE INTO people_cards (filing_id, symbol, card, created_at) VALUES (?, ?, ?, ?)",
            (f["id"], f["symbol"], card.model_dump_json(), now_iso()),
        )
        conn.commit()
        stats["cards"] += 1
    return stats
