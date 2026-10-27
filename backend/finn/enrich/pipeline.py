"""Enrich collected filings with AI, then export.

    uv run python -m finn.enrich                    # everything, then export
    uv run python -m finn.enrich --only results     # results cards only (XBRL needs no keys)
    uv run python -m finn.enrich --dry-run          # what would be sent, and what it would cost
    uv run python -m finn.enrich --limit 12         # cap the triage work, for a first test

Stages, in dependency order, so the final triage prompt sees everything known
1. tables   Standard financial tables for the portfolio from screener.in, cached 12 hours.
            They give company size for triage and the cross-check for results cards.
2. events   Every event each filing contains, found by reading it, and which filings are
            copies of the same letter. No model.
3. results  The results card for each company that reported in the window.
4. people   Bios for leadership changes, from the filings' own profile sections, for any
            filing that contains one.
5. triage   Category, events, tier, title, summary and why-it-matters, with the results
            numbers and bios from steps 3 and 4 in the prompt.

Runs without API keys too: results cards still come from XBRL or screener.in, and the
AI stages report what they would have done.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import time

from finn import export, net
from finn.ai.llm import LLM, env_summary
from finn.collectors import fundamentals
from finn.config import FILINGS_LOOKBACK_DAYS, PORTFOLIO
from finn.enrich import events, people, results, triage
from finn.store import Run, connect

STAGES = ("tables", "events", "results", "people", "triage")
TABLES_MAX_AGE_HOURS = 12


def refresh_tables(conn) -> dict:
    stats = {"refreshed": [], "fresh": 0, "failed": []}
    cutoff = time.time() - TABLES_MAX_AGE_HOURS * 3600
    for c in PORTFOLIO:
        row = conn.execute(
            "SELECT MAX(fetched_at) FROM financials WHERE symbol = ?", (c.symbol,)
        ).fetchone()
        if (
            row[0]
            and time.mktime(time.strptime(row[0][:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
            > cutoff
        ):
            stats["fresh"] += 1
            continue
        try:
            fundamentals.run(conn, c, transcripts=0, annual_reports=0)
            stats["refreshed"].append(c.symbol)
        except Exception as exc:  # noqa: BLE001
            logging.warning("tables for %s failed: %s", c.symbol, exc)
            stats["failed"].append(c.symbol)
    return stats


def run(
    conn,
    llm: LLM | None,
    stages=STAGES,
    days: int = FILINGS_LOOKBACK_DAYS,
    limit: int | None = None,
) -> dict:
    out: dict = {}
    ai_ready = llm is not None and llm.configured
    if "tables" in stages:
        out["tables"] = refresh_tables(conn)
    if "events" in stages:
        out["events"] = events.run(conn, days)
    if "results" in stages:
        cards = []
        for symbol, quarter in results.due(conn, days):
            card = results.build(conn, llm, symbol, quarter)
            cards.append(f"{symbol} {quarter}: {card.source if card else 'none'}"
                         + (f", verified={card.verified}" if card else ""))  # fmt: skip
        out["results"] = cards
    if "people" in stages:
        if ai_ready:
            out["people"] = people.run(conn, llm, days)
        else:
            out["people"] = {"skipped": "no API keys", "pending": len(people.pending(conn, days))}
    if "triage" in stages:
        if ai_ready:
            out["triage"] = triage.run(conn, llm, days, limit)
        else:
            n = len(triage.pending(conn, days))
            out["triage"] = {
                "skipped": "no API keys",
                "pending": n,
                "would_call": math.ceil(n / triage.BATCH),
            }
    if llm is not None:
        out["ai"] = llm.stats
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--only", choices=STAGES, nargs="+")
    ap.add_argument("--days", type=int, default=FILINGS_LOOKBACK_DAYS)
    ap.add_argument("--limit", type=int, help="cap the number of filings sent to triage")
    ap.add_argument(
        "--dry-run", action="store_true", help="report the work and its cost, call nothing"
    )
    ap.add_argument("--no-export", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "google_genai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    conn = connect()
    if args.dry_run:
        todo = triage.pending(conn, args.days)
        report = {
            "keys": env_summary(),
            "triage_filings": len(todo),
            "triage_calls": math.ceil(len(todo) / triage.BATCH),
            "people_filings": len(people.pending(conn, args.days)),
            "results_due": [f"{s} {q}" for s, q in results.due(conn, args.days)],
        }
        print(json.dumps(report, indent=2))
        return 0
    llm = LLM.from_env(conn)
    if not llm.configured:
        logging.warning("no API keys found in backend/.env; AI stages will be skipped")
    with Run(conn, "enrich") as rec:
        rec.stats = run(conn, llm, args.only or STAGES, args.days, args.limit)
        if not args.no_export:
            rec.stats["export"] = export.run(conn)
        rec.stats["requests"] = {c.name: c.requests_made for c in net.all_clients()}
    print(json.dumps(rec.stats, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
