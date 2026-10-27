"""Write the static JSON files the app loads, validated against `contracts`.

Static-first (decision D8): the Push screens read these files straight from the web
host, so they open instantly and never wait for a sleeping free-tier server.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel

from finn import contracts as C
from finn.config import (
    DEFAULT_PRICE_MOVE_PCT,
    DEFAULT_VOLUME_MULTIPLE,
    EXPORT_DIR,
    EXPORT_PRICE_SESSIONS,
    FILINGS_LOOKBACK_DAYS,
    PORTFOLIO,
    VOLUME_BASELINE_SESSIONS,
)
from finn.enrich import events, results, score
from finn.store import now_iso


def _write(model: BaseModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=1), encoding="utf-8")


def holdings(conn: sqlite3.Connection) -> list[C.Holding]:
    out = []
    for c in PORTFOLIO:
        rows = conn.execute(
            "SELECT * FROM prices WHERE symbol = ? ORDER BY date DESC LIMIT ?",
            (c.symbol, EXPORT_PRICE_SESSIONS),
        ).fetchall()[::-1]
        last = rows[-1] if rows else None
        out.append(
            C.Holding(
                symbol=c.symbol,
                name=c.name,
                sector=c.sector,
                size=c.size,
                last_date=last["date"] if last else None,
                close=last["close"] if last else None,
                ret_pct=last["ret_pct"] if last else None,
                vol_ratio=last["vol_ratio"] if last else None,
                series=[
                    C.PricePoint(
                        date=r["date"],
                        close=r["close"],
                        ret_pct=r["ret_pct"],
                        vol_ratio=r["vol_ratio"],
                        corp_action=r["corp_action"],
                    )
                    for r in rows
                ],
                source_url=last["source_url"]
                if last
                else f"https://finance.yahoo.com/quote/{c.yahoo}",
            )
        )
    return out


MARKET_CLOSE = "15:30"


def reaction(conn: sqlite3.Connection, symbol: str, filed_at: str) -> C.PriceReaction | None:
    """The first session that could react: the filing day if filed before the close, else the next."""
    day, clock = filed_at[:10], filed_at[11:16]
    op = ">=" if clock < MARKET_CLOSE else ">"
    row = conn.execute(
        f"SELECT date, ret_pct, vol_ratio, corp_action FROM prices WHERE symbol = ? AND date {op} ? "
        "ORDER BY date LIMIT 1",
        (symbol, day),
    ).fetchone()
    if not row or row["corp_action"]:
        return None
    return C.PriceReaction(session=row["date"], ret_pct=row["ret_pct"], vol_ratio=row["vol_ratio"])


_INSIGHT_COLS = (
    "category, tier, title, summary, why_it_matters, sentiment, amount_inr_crore, model, events"
)


def _insight_for(conn: sqlite3.Connection, filing_id: str) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT {_INSIGHT_COLS} FROM filing_insights WHERE filing_id = ?", (filing_id,)
    ).fetchone()


def _people_for(conn: sqlite3.Connection, filing_id: str) -> C.PeopleCard | None:
    row = conn.execute("SELECT card FROM people_cards WHERE filing_id = ?", (filing_id,)).fetchone()
    return C.PeopleCard.model_validate_json(row["card"]) if row else None


def _build(conn: sqlite3.Connection, r: sqlite3.Row) -> C.Filing:
    detected, duplicate_of = events.load(conn, r["id"])
    # A copy of an earlier letter shows what was concluded about the original.
    source_id = duplicate_of or r["id"]
    ins = _insight_for(conn, source_id) or (_insight_for(conn, r["id"]) if duplicate_of else None)
    people_card = _people_for(conn, source_id)
    category = (ins["category"] if ins else None) or r["category"]
    tier = (ins["tier"] if ins else None) or r["tier"]
    event_list = json.loads(ins["events"]) if ins and ins["events"] else list(detected)
    if category and category not in event_list:
        event_list.insert(0, category)
    lead = events.lead_event(event_list, category)
    event_list = [lead] + [e for e in event_list if e != lead] if lead else event_list

    insight = None
    if ins and ins["summary"]:
        insight = C.Insight(
            title=ins["title"], summary=ins["summary"], why_it_matters=ins["why_it_matters"],
            sentiment=ins["sentiment"] or "neutral", amount_inr_crore=ins["amount_inr_crore"], model=ins["model"] or "",
        )  # fmt: skip
    cards: list[C.ResultsCard | C.PeopleCard] = []
    if "results" in event_list and (tier == "must_see" or "results" in detected):
        q = results.quarter_end_before(date.fromisoformat(r["filed_at"][:10]))
        card = results.load(conn, r["symbol"], q.isoformat())
        if card:
            cards.append(card)
    if people_card:
        cards.append(people_card)
    react = reaction(conn, r["symbol"], r["filed_at"])
    roles = " ".join(c.role for c in people_card.changes) if people_card else ""
    text = " ".join(x or "" for x in (insight.title if insight else "", insight.summary if insight else "",
                                      r["headline"], r["exchange_label"], roles))  # fmt: skip
    return C.Filing(
        id=r["id"], symbol=r["symbol"], exchange=r["exchange"], filed_at=r["filed_at"],
        exchange_label=r["exchange_label"], headline=r["headline"], category=category, tier=tier,
        classified_by="ai" if ins else r["classified_by"], rule=r["rule"],
        needs_ai=bool(r["needs_ai"]) and insight is None, text_quality=r["text_quality"],
        attachment_url=r["attachment_url"], source_url=r["source_url"], insight=insight, events=event_list,
        cards=cards, price_reaction=react, score=score.score(tier, lead, text, ins["sentiment"] if ins else None, react),
        group_id=score.group_id(r["symbol"], lead, r["filed_at"]), duplicate_of=duplicate_of,
    )  # fmt: skip


def _merge_groups(items: list[C.Filing]) -> None:
    """One lead per group, carrying every distinct card in the group, shown once."""
    groups: dict[str, list[C.Filing]] = {}
    for f in items:
        groups.setdefault(f.group_id, []).append(f)
    for members in groups.values():
        # Highest score leads; on a tie, an original beats a copy and earlier beats later.
        members.sort(key=lambda f: (-f.score, f.duplicate_of is not None, f.filed_at))
        lead, merged, seen = members[0], [], set()
        for f in members:
            for card in f.cards:
                if isinstance(card, C.ResultsCard):
                    key = ("results", card.period_end)
                    if key not in seen:
                        seen.add(key)
                        merged.append(card)
                else:
                    fresh = [
                        c
                        for c in card.changes
                        if ("person", c.person.lower(), c.change) not in seen
                    ]
                    seen.update(("person", c.person.lower(), c.change) for c in fresh)
                    if fresh:
                        merged.append(C.PeopleCard(changes=fresh))
            f.group_lead = f is lead
            if f is not lead:
                f.cards = []
        lead.cards = merged


def filings(conn: sqlite3.Connection, days: int = FILINGS_LOOKBACK_DAYS) -> list[C.Filing]:
    since = (date.today() - timedelta(days=days)).isoformat()
    symbols = [c.symbol for c in PORTFOLIO]
    rows = conn.execute(
        f"SELECT * FROM filings WHERE filed_at >= ? AND symbol IN ({','.join('?' * len(symbols))}) "
        "ORDER BY filed_at DESC",
        (since, *symbols),
    ).fetchall()
    items = [_build(conn, r) for r in rows]
    _merge_groups(items)
    return items


def ai_stats(conn: sqlite3.Connection) -> C.AIStats:
    rows = conn.execute(
        "SELECT model, COUNT(*) AS n, COALESCE(SUM(input_tokens), 0) AS i, COALESCE(SUM(output_tokens), 0) AS o "
        "FROM ai_usage WHERE ok = 1 GROUP BY model"
    ).fetchall()
    cached = conn.execute("SELECT COUNT(*) FROM ai_cache").fetchone()[0]
    return C.AIStats(
        calls=sum(r["n"] for r in rows),
        input_tokens=sum(r["i"] for r in rows),
        output_tokens=sum(r["o"] for r in rows),
        by_model={r["model"]: r["n"] for r in rows},
        cached_answers=cached,
    )


def run(conn: sqlite3.Connection, out_dir: Path = EXPORT_DIR) -> dict:
    hs = holdings(conn)
    fs = filings(conn)
    latest = max((h.last_date for h in hs if h.last_date), default=None)
    meta = C.Meta(
        generated_at=now_iso(),
        latest_session=latest,
        filings_window_days=FILINGS_LOOKBACK_DAYS,
        counts={
            "holdings": len(hs),
            "filings": len(fs),
            # By event, not by filing: one event can arrive as six copies of one letter.
            "events": sum(f.group_lead for f in fs),
            "duplicates": sum(f.duplicate_of is not None for f in fs),
            "must_see": sum(f.group_lead and f.tier == "must_see" for f in fs),
            "glance": sum(f.group_lead and f.tier == "glance" for f in fs),
            "routine": sum(f.group_lead and f.tier == "routine" for f in fs),
            "unsorted": sum(f.group_lead and f.tier is None for f in fs),
        },
        alert_defaults=C.AlertDefaults(
            price_move_pct=DEFAULT_PRICE_MOVE_PCT,
            volume_multiple=DEFAULT_VOLUME_MULTIPLE,
            volume_baseline_sessions=VOLUME_BASELINE_SESSIONS,
        ),
        ai=ai_stats(conn),
        sources=[
            "Prices: Yahoo Finance end-of-day, adjusted for splits and dividends",
            "Corporate actions and filings: NSE, with BSE as fallback",
            "Results numbers: exchange XBRL first, then the results PDF, checked against screener.in",
            "Summaries and bios: Gemini, from the filing text only",
        ],
    )
    _write(C.Portfolio(holdings=hs), out_dir / "portfolio.json")
    _write(C.Filings(filings=fs), out_dir / "filings.json")
    _write(meta, out_dir / "meta.json")
    schema = {
        name: model.model_json_schema()
        for name, model in (("portfolio", C.Portfolio), ("filings", C.Filings), ("meta", C.Meta))
    }
    (out_dir / "schema.json").write_text(json.dumps(schema, indent=1), encoding="utf-8")
    return meta.counts
