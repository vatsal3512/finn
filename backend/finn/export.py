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


def filings(conn: sqlite3.Connection, days: int = FILINGS_LOOKBACK_DAYS) -> list[C.Filing]:
    since = (date.today() - timedelta(days=days)).isoformat()
    symbols = [c.symbol for c in PORTFOLIO]
    rows = conn.execute(
        f"SELECT * FROM filings WHERE filed_at >= ? AND symbol IN ({','.join('?' * len(symbols))}) "
        "ORDER BY filed_at DESC",
        (since, *symbols),
    ).fetchall()
    return [
        C.Filing(
            id=r["id"],
            symbol=r["symbol"],
            exchange=r["exchange"],
            filed_at=r["filed_at"],
            exchange_label=r["exchange_label"],
            headline=r["headline"],
            category=r["category"],
            tier=r["tier"],
            classified_by=r["classified_by"],
            rule=r["rule"],
            needs_ai=bool(r["needs_ai"]),
            text_quality=r["text_quality"],
            attachment_url=r["attachment_url"],
            source_url=r["source_url"],
        )
        for r in rows
    ]


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
        sources=[
            "Prices: Yahoo Finance end-of-day, adjusted for splits and dividends",
            "Corporate actions and filings: NSE, with BSE as fallback",
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
