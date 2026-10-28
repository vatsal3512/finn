"""Refresh everything Push needs, then export it for the app.

    uv run python -m finn.refresh                 # full refresh of the portfolio
    uv run python -m finn.refresh --days 7        # shorter filings window
    uv run python -m finn.refresh --only filings  # one stage
    uv run python -m finn.refresh --symbols HDFCBANK MARUTI

Stages run in dependency order: corporate actions first, because prices use them to mark
ex-dates; filings next; then enrichment (results cards, AI triage and bios, see
finn.enrich); export last. A failing company is logged and skipped, so one bad source
never blocks the rest. Each run is recorded in the `runs` table.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from finn import export, net
from finn.ai.llm import LLM
from finn.collectors import corp_actions, filings, prices
from finn.config import BY_SYMBOL, FILINGS_LOOKBACK_DAYS, PORTFOLIO
from finn.enrich.pipeline import run as enrich_run
from finn.store import Run, connect, now_iso, upsert

STAGES = ("corp_actions", "prices", "filings", "enrich", "export")


def seed_companies(conn) -> None:
    """Make sure every configured company has a row, without overwriting fetched fields."""
    for c in PORTFOLIO:
        exists = conn.execute("SELECT 1 FROM companies WHERE symbol = ?", (c.symbol,)).fetchone()
        if not exists:
            upsert(conn, "companies", [{"symbol": c.symbol, "name": c.name, "sector": c.sector,
                   "size": c.size, "role": c.role, "updated_at": now_iso()}], ("symbol",))  # fmt: skip
    conn.commit()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--days", type=int, default=FILINGS_LOOKBACK_DAYS, help="filings window in days"
    )
    ap.add_argument("--only", choices=STAGES, nargs="+", help="run only these stages")
    ap.add_argument("--symbols", nargs="+", help="limit to these portfolio symbols")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("yfinance", "urllib3", "peewee"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    companies = [BY_SYMBOL[s.upper()] for s in args.symbols] if args.symbols else list(PORTFOLIO)
    stages = args.only or STAGES
    conn = connect()
    seed_companies(conn)
    failed = []
    with Run(conn, "refresh " + " ".join(argv or sys.argv[1:])) as run:
        for stage in STAGES:
            if stage not in stages:
                continue
            t0 = time.perf_counter()
            # One source failing, such as NSE refusing a cloud server, must not stop the
            # others: the run exports and commits whatever it could get.
            try:
                if stage == "corp_actions":
                    run.stats[stage] = corp_actions.run(conn, companies)
                elif stage == "prices":
                    run.stats[stage] = prices.run(conn, companies)
                elif stage == "filings":
                    run.stats[stage] = filings.run(conn, companies, days=args.days)
                elif stage == "enrich":
                    run.stats[stage] = enrich_run(conn, LLM.from_env(conn), days=args.days)
                elif stage == "export":
                    run.stats[stage] = export.run(conn)
            except Exception as exc:  # noqa: BLE001 - recorded, and the next stage runs
                logging.exception("%s failed", stage)
                run.stats[stage] = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
                failed.append(stage)
            run.stats[stage]["seconds"] = round(time.perf_counter() - t0, 1)
            logging.info("%s done: %s", stage, json.dumps(run.stats[stage], default=str))
        run.stats["requests"] = {c.name: c.requests_made for c in net.all_clients()}
        run.stats["failed_stages"] = failed
    print(json.dumps(run.stats, indent=2, default=str))
    return 1 if "export" in failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
