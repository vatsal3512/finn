"""Does research give the same report twice? The whole pipeline, run three times.

Each run reads every transcript afresh and judges afresh: the extraction and judge prompt
versions get a run suffix, so nothing comes back from the cache. Data from the accounts is
the same each time, so any difference is the models'.

Promises are matched across runs by metric and period ("Revenue growth", "FY27").

A run that could not read every call, or judge, because the free-tier models were busy is
not a fair comparison. It is retried: every call that did answer is cached under its run's
version, so a retry asks only for what is missing. A run still incomplete after the
retries is reported as such and left out of the comparison.
"""

from __future__ import annotations

import re
import time
from itertools import combinations

from finn.research import engine, extract, judge

COMPANIES = ("KAYNES", "ASIANPAINT")
ATTEMPTS = 4
INCOMPLETE = ("could not be read", "reasoning model was unavailable")


def _key(p) -> tuple[str, str]:
    return re.sub(r"[^a-z]+", " ", p.metric.lower()).strip(), (p.period or "").upper()


def run(companies=COMPANIES, runs: int = 3) -> dict:
    base = extract.PROMPT_VERSION, judge.PROMPT_VERSION
    out = {}
    try:
        for symbol in companies:
            reports, incomplete = [], []
            for k in range(1, runs + 1):
                extract.PROMPT_VERSION = f"{base[0]}+eval-r{k}"
                judge.PROMPT_VERSION = f"{base[1]}+eval-r{k}"
                report = _complete_run(symbol, k, runs)
                if report:
                    reports.append(report)
                else:
                    incomplete.append(k)
            out[symbol] = compare(reports) if len(reports) >= 2 else {}
            out[symbol]["incomplete_runs"] = incomplete
    finally:
        extract.PROMPT_VERSION, judge.PROMPT_VERSION = base
    return out


def _complete_run(symbol: str, k: int, runs: int):
    for attempt in range(1, ATTEMPTS + 1):
        print(f"stability: {symbol} run {k} of {runs}, attempt {attempt}")
        try:
            report = engine.research(symbol)
        except RuntimeError as exc:
            print(f"  failed: {exc}")
        else:
            if not any(m in n for n in report.notes for m in INCOMPLETE):
                return report
            print(f"  incomplete: {report.notes}")
        time.sleep(180)  # the models' busy window
    return None


def compare(reports) -> dict:
    keys = [{_key(p): p for p in r.promises} for r in reports]
    sets = [set(k) for k in keys]
    common = set.intersection(*sets)
    union = set.union(*sets)
    same_verdict = [k for k in common if len({ks[k].verdict for ks in keys}) == 1]
    return {
        "promises_per_run": [len(r.promises) for r in reports],
        "found_in_every_run": len(common),
        "found_in_any_run": len(union),
        "pairwise_overlap": [round(len(a & b) / len(a | b), 2) for a, b in combinations(sets, 2)],
        "same_verdict_when_found_every_time": f"{len(same_verdict)} of {len(common)}",
        "verdicts_that_moved": [
            {"promise": " ".join(k), "verdicts": [ks[k].verdict for ks in keys]}
            for k in sorted(common - set(same_verdict))
        ],
        "only_in_some_runs": [" ".join(k) for k in sorted(union - common)],
        "quotes_verified": [
            f"{r.stats.quotes_verified} of {r.stats.claims_found}" for r in reports
        ],
        "models": [r.stats.models for r in reports],
        "narratives": [r.narrative for r in reports],
    }
