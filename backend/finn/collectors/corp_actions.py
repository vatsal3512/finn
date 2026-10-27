"""Corporate actions from NSE: the dates on which a price move is not a real move.

Yahoo Finance adjusts history for splits and bonuses, but not for demergers. Vedanta's
demerger on 30 April 2026 shows up as a 65% one-day "crash". Marking ex-dates here lets
alerts skip those days instead of telling the investor something false.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import date, datetime, timedelta

from finn import net
from finn.config import CORP_ACTION_LOOKBACK_DAYS, Company
from finn.store import now_iso, upsert

log = logging.getLogger(__name__)

API = "https://www.nseindia.com/api/corporates-corporateActions"

# Order matters: "Bonus 1:1 And Face Value Split" should read as a bonus, not a dividend.
KINDS = (
    ("demerger", r"demerger|scheme of arrangement"),
    ("bonus", r"bonus"),
    ("split", r"split|sub-?division"),
    ("consolidation", r"consolidation"),
    ("rights", r"rights"),
    ("capital_reduction", r"reduction of capital|capital reduction"),
    ("buyback", r"buy ?back"),
    ("dividend", r"dividend"),
)

# Actions that change what one share is worth, so the price series has a break.
PRICE_BREAKS = {"demerger", "bonus", "split", "consolidation", "rights", "capital_reduction"}


def kind_of(subject: str) -> str:
    for kind, pattern in KINDS:
        if re.search(pattern, subject, re.I):
            return kind
    return "other"


def _iso(d: str) -> str | None:
    try:
        return datetime.strptime(d, "%d-%b-%Y").date().isoformat()
    except TypeError, ValueError:
        return None


def fetch(company: Company, days: int = CORP_ACTION_LOOKBACK_DAYS) -> list[dict]:
    end = date.today()
    start = end - timedelta(days=days)
    params = {
        "index": "equities",
        "symbol": company.symbol,
        "from_date": start.strftime("%d-%m-%Y"),
        "to_date": end.strftime("%d-%m-%Y"),
    }
    data = net.nse().get_json(API, params) or []
    fetched = now_iso()
    rows = []
    for item in data:
        ex = _iso(item.get("exDate", ""))
        subject = (item.get("subject") or "").strip()
        if not ex or not subject:
            continue
        rows.append(
            {
                "symbol": company.symbol,
                "ex_date": ex,
                "subject": subject,
                "kind": kind_of(subject),
                "record_date": _iso(item.get("recDate", "")),
                "source_url": f"{API}?symbol={company.symbol}",
                "fetched_at": fetched,
            }
        )
    return rows


def run(conn: sqlite3.Connection, companies: list[Company]) -> dict:
    stats = {"companies": 0, "actions": 0, "failed": []}
    for company in companies:
        try:
            rows = fetch(company)
        except (net.HTTPError, net.TransientHTTPError) as exc:
            log.warning("corporate actions for %s failed: %s", company.symbol, exc)
            stats["failed"].append(company.symbol)
            continue
        stats["actions"] += upsert(conn, "corp_actions", rows, ("symbol", "ex_date", "subject"))
        stats["companies"] += 1
    conn.commit()
    return stats


def price_breaks(conn: sqlite3.Connection, symbol: str) -> dict[str, str]:
    """ex_date -> kind, for actions that break the price series."""
    rows = conn.execute(
        "SELECT ex_date, kind FROM corp_actions WHERE symbol = ?", (symbol,)
    ).fetchall()
    return {r["ex_date"]: r["kind"] for r in rows if r["kind"] in PRICE_BREAKS}
