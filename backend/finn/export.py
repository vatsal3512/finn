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
from finn.enrich import results, score
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


def filings(conn: sqlite3.Connection, days: int = FILINGS_LOOKBACK_DAYS) -> list[C.Filing]:
    since = (date.today() - timedelta(days=days)).isoformat()
    symbols = [c.symbol for c in PORTFOLIO]
    rows = conn.execute(
        "SELECT f.*, i.category AS ai_category, i.tier AS ai_tier, i.title, i.summary, i.why_it_matters, "
        "i.sentiment, i.amount_inr_crore, i.model AS ai_model, p.card AS people_card "
        "FROM filings f LEFT JOIN filing_insights i ON i.filing_id = f.id "
        "LEFT JOIN people_cards p ON p.filing_id = f.id "
        f"WHERE f.filed_at >= ? AND f.symbol IN ({','.join('?' * len(symbols))}) ORDER BY f.filed_at DESC",
        (since, *symbols),
    ).fetchall()
    out = []
    for r in rows:
        category = r["ai_category"] or r["category"]
        tier = r["ai_tier"] or r["tier"]
        insight = None
        if r["summary"]:
            insight = C.Insight(
                title=r["title"], summary=r["summary"], why_it_matters=r["why_it_matters"],
                sentiment=r["sentiment"] or "neutral", amount_inr_crore=r["amount_inr_crore"], model=r["ai_model"] or "",
            )  # fmt: skip
        card: C.ResultsCard | C.PeopleCard | None = None
        if r["people_card"]:
            card = C.PeopleCard.model_validate_json(r["people_card"])
        elif category == "results" and tier == "must_see":
            q = results.quarter_end_before(date.fromisoformat(r["filed_at"][:10]))
            card = results.load(conn, r["symbol"], q.isoformat())
        react = reaction(conn, r["symbol"], r["filed_at"])
        text = " ".join(
            x or "" for x in (r["title"], r["summary"], r["headline"], r["exchange_label"])
        )
        out.append(
            C.Filing(
                id=r["id"],
                symbol=r["symbol"],
                exchange=r["exchange"],
                filed_at=r["filed_at"],
                exchange_label=r["exchange_label"],
                headline=r["headline"],
                category=category,
                tier=tier,
                classified_by="ai" if r["ai_tier"] else r["classified_by"],
                rule=r["rule"],
                needs_ai=bool(r["needs_ai"]) and insight is None,
                text_quality=r["text_quality"],
                attachment_url=r["attachment_url"],
                source_url=r["source_url"],
                insight=insight,
                card=card,
                price_reaction=react,
                score=score.score(tier, category, text, r["sentiment"], react),
                group_id=score.group_id(r["symbol"], category, r["filed_at"]),
            )  # fmt: skip
        )
    return out


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
            "must_see": sum(f.tier == "must_see" for f in fs),
            "glance": sum(f.tier == "glance" for f in fs),
            "routine": sum(f.tier == "routine" for f in fs),
            "unsorted": sum(f.tier is None for f in fs),
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
