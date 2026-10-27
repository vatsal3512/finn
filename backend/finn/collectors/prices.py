"""End-of-day prices from Yahoo Finance, with the two numbers alerts are judged on.

For each session we store the close-to-close move and the volume ratio: today's volume
divided by the average of the previous 20 sessions. Today is excluded from its own
baseline, otherwise a spike would dilute the very average it is compared with.

The investor's thresholds are applied in the app, not here, so changing "unusual" from
2x to 3x volume never needs a server or a re-run.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from finn.collectors.corp_actions import price_breaks
from finn.config import PRICE_HISTORY_DAYS, VOLUME_BASELINE_SESSIONS, Company
from finn.store import now_iso, upsert

log = logging.getLogger(__name__)

SOURCE = "https://finance.yahoo.com/quote/{ticker}/history"


def compute_metrics(
    df: pd.DataFrame, breaks: dict[str, str], window: int = VOLUME_BASELINE_SESSIONS
) -> pd.DataFrame:
    """Add ret_pct, vol_ratio and corp_action to an OHLCV frame indexed by date."""
    out = df.copy()
    out["ret_pct"] = out["Close"].pct_change() * 100
    baseline = out["Volume"].shift(1).rolling(window, min_periods=window).mean()
    out["vol_ratio"] = out["Volume"] / baseline.where(baseline > 0)
    days = pd.Index(out.index).map(lambda d: pd.Timestamp(d).date().isoformat())
    # object dtype keeps None as None; pandas 3 would otherwise turn it into NaN.
    out["corp_action"] = pd.Series([breaks.get(d) for d in days], index=out.index, dtype=object)
    return out


def _download(companies: list[Company], start: date) -> dict[str, pd.DataFrame]:
    tickers = [c.yahoo for c in companies]
    frames: dict[str, pd.DataFrame] = {}
    raw = yf.download(
        tickers,
        start=start.isoformat(),
        auto_adjust=True,
        group_by="ticker",
        threads=True,
        progress=False,
    )
    for c in companies:
        try:
            frame = raw[c.yahoo] if len(tickers) > 1 else raw
            frame = frame.dropna(subset=["Close"])
        except KeyError:
            frame = pd.DataFrame()
        if frame.empty:  # batch downloads drop tickers on timeouts; retry alone
            log.info("retrying %s on its own", c.yahoo)
            frame = yf.Ticker(c.yahoo).history(start=start.isoformat(), auto_adjust=True)
            frame = frame.dropna(subset=["Close"]) if not frame.empty else frame
        if not frame.empty:
            frames[c.symbol] = frame
    return frames


def run(conn: sqlite3.Connection, companies: list[Company]) -> dict:
    start = date.today() - timedelta(days=PRICE_HISTORY_DAYS)
    frames = _download(companies, start)
    fetched = now_iso()
    stats = {"companies": len(frames), "rows": 0, "missing": [], "latest_session": None}
    for c in companies:
        frame = frames.get(c.symbol)
        if frame is None:
            stats["missing"].append(c.symbol)
            continue
        m = compute_metrics(frame, price_breaks(conn, c.symbol))
        rows = [
            {
                "symbol": c.symbol,
                "date": pd.Timestamp(ix).date().isoformat(),
                "open": _num(r["Open"]),
                "high": _num(r["High"]),
                "low": _num(r["Low"]),
                "close": float(r["Close"]),
                "volume": int(r["Volume"]) if pd.notna(r["Volume"]) else None,
                "ret_pct": _num(r["ret_pct"], 3),
                "vol_ratio": _num(r["vol_ratio"], 3),
                "corp_action": r["corp_action"],
                "source_url": SOURCE.format(ticker=c.yahoo),
                "fetched_at": fetched,
            }
            for ix, r in m.iterrows()
        ]
        stats["rows"] += upsert(conn, "prices", rows, ("symbol", "date"))
        last = rows[-1]["date"] if rows else None
        if last and (stats["latest_session"] is None or last > stats["latest_session"]):
            stats["latest_session"] = last
    conn.commit()
    return stats


def _num(v, digits: int = 2) -> float | None:
    return round(float(v), digits) if pd.notna(v) else None
