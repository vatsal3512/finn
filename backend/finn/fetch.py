"""Fetch fundamentals and primary documents for any NSE ticker.

    uv run python -m finn.fetch INFY
    uv run python -m finn.fetch KAYNES HFCL --transcripts 4 --annual-reports 1
    uv run python -m finn.fetch --research-set      # the five demo research companies

Works on companies outside the configured lists too, which is how the research view
handles a ticker the graders pick.
"""

from __future__ import annotations

import argparse
import json
import logging

from finn import net
from finn.collectors import fundamentals
from finn.config import ANNUAL_REPORTS_PER_COMPANY, RESEARCH, TRANSCRIPTS_PER_COMPANY
from finn.store import Run, connect


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("symbols", nargs="*", help="NSE symbols")
    ap.add_argument("--research-set", action="store_true", help="fetch the five research companies")
    ap.add_argument("--transcripts", type=int, default=TRANSCRIPTS_PER_COMPANY)
    ap.add_argument("--annual-reports", type=int, default=ANNUAL_REPORTS_PER_COMPANY)
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    symbols = [s.upper() for s in args.symbols] + (
        [c.symbol for c in RESEARCH] if args.research_set else []
    )
    if not symbols:
        ap.error("give at least one symbol, or --research-set")
    conn = connect()
    results = []
    with Run(conn, "fetch " + " ".join(symbols)) as run:
        for s in symbols:
            try:
                results.append(
                    fundamentals.run(
                        conn, fundamentals.company_for(s), args.transcripts, args.annual_reports
                    )
                )
            except Exception as exc:  # noqa: BLE001 - report per symbol
                logging.error("%s failed: %s", s, exc)
                results.append({"symbol": s, "error": str(exc)})
        run.stats = {
            "results": results,
            "requests": {c.name: c.requests_made for c in net.all_clients()},
        }
    print(json.dumps(results, indent=2))
    return 0 if all("error" not in r for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
