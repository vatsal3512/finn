"""uv run python -m finn.evals [triage|research|stability|all] [--no-second]

Each part writes its full results, every flag included, to finn/evals/results/.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from finn.evals import research, stability, triage

RESULTS = Path(__file__).parent / "results"


def save(name: str, result: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{name}.json").write_text(
        json.dumps(result, indent=1, ensure_ascii=False, default=str), encoding="utf-8"
    )
    keep = ("reports", "answers", "quotes", "numbers", "duplicate_quotes", "second_model")
    summary = result.get("summary") or {k: result[k] for k in keep if k in result} or result
    print(json.dumps(summary, indent=1, ensure_ascii=False, default=str)[:4000])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("part", choices=("triage", "research", "stability", "all"))
    ap.add_argument("--no-second", action="store_true", help="skip the second-model check")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    if args.part in ("triage", "all"):
        save("triage", triage.run(second_model=not args.no_second))
    if args.part in ("research", "all"):
        save("research", research.run(second_model=not args.no_second))
    if args.part in ("stability", "all"):
        save("stability", stability.run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
