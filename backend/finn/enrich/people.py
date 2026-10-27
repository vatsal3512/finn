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
from finn.store import now_iso

log = logging.getLogger(__name__)

PROMPT_VERSION = "people-v1"
LOOKBACK_DAYS = 120

SYSTEM = """You extract leadership changes from Indian exchange filings.
List each person who is appointed, resigns, retires, ceases or is redesignated.
- Use only the text given. Never use outside knowledge about the person.
- profile: at most 45 words, from the filing's own profile or background section, or
  null if the filing has none. Keep concrete facts: past employers, roles, years.
- previous_roles: up to 5, as "Role, Organisation".
- change must be one of: appointment, resignation, retirement, cessation, redesignation, other.
- effective_date as YYYY-MM-DD if stated."""


class Extract(BaseModel):
    changes: list[PersonChange]


def _excerpt(text: str) -> str:
    """The announcement itself plus the profile section, wherever it sits."""
    head = text[:2500]
    m = re.search(r"brief profile|profile of|background", text, re.I)
    if m and m.start() > 2000:
        return head + "\n...\n" + text[max(0, m.start() - 800) : m.start() + 4000]
    return text[:6500]


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
    since = (date.today() - timedelta(days=days)).isoformat()
    return conn.execute(
        "SELECT f.* FROM filings f LEFT JOIN filing_insights i ON i.filing_id = f.id "
        "LEFT JOIN people_cards p ON p.filing_id = f.id "
        "WHERE COALESCE(i.category, f.category) = 'management_change' AND f.filed_at >= ? "
        "AND f.text_path IS NOT NULL AND f.text_quality = 'ok' AND p.filing_id IS NULL",
        (since,),
    ).fetchall()


def run(conn: sqlite3.Connection, llm: LLM, days: int = 30) -> dict:
    todo = pending(conn, days)
    stats = {"pending": len(todo), "cards": 0, "profiles_from_earlier_filings": 0}
    for f in todo:
        try:
            ext = _extract(llm, (DATA_DIR / f["text_path"]).read_text(encoding="utf-8"))
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
