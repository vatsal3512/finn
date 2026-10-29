"""Research companies and write their reports where the app reads them.

uv run python -m finn.research KAYNES
uv run python -m finn.research INFY LT --refresh
uv run python -m finn.research --all        # the research set and the portfolio
uv run python -m finn.research --ask 12     # "ask about this" for the top 12 Push cards
uv run python -m finn.research --update 2   # rebuild up to 2 reports their companies have outdated
"""

from __future__ import annotations

import argparse
import json
import logging

from finn.ai.llm import LLM
from finn.config import EXPORT_DIR, PORTFOLIO, RESEARCH
from finn.contracts import AskAnswers, ResearchIndex, ResearchIndexEntry, ResearchReport
from finn.research import update
from finn.research.ask import ask
from finn.research.engine import research
from finn.store import connect

OUT = EXPORT_DIR / "research"


def write_index() -> None:
    """One small file listing every report, so the app can show the menu without loading all."""
    rows = []
    for f in sorted(OUT.glob("*.json")):
        if f.name == "index.json":
            continue
        r = ResearchReport.model_validate_json(f.read_text(encoding="utf-8"))
        verdicts = [p.verdict for p in r.promises]
        rows.append(ResearchIndexEntry(
            symbol=r.symbol, name=r.name, generated_at=r.generated_at, promises=len(verdicts),
            missed=verdicts.count("missed"), kept=sum(v in ("met", "beat") for v in verdicts),
            pending=sum(v in ("pending", "on_track", "at_risk") for v in verdicts),
        ))  # fmt: skip
    (OUT / "index.json").write_text(
        ResearchIndex(reports=rows).model_dump_json(indent=1), encoding="utf-8"
    )


# The question each kind of Push card asks of management's own words.
QUESTIONS = {
    "results": "What had management said on recent calls about revenue and margins for this "
    "period, and does this result match it?",
    "management_change": "What has management said on recent calls about leadership, "
    "succession or this role?",
    "M&A": "What has management said about this deal: its purpose, its price and how it fits "
    "the plan?",
    "fund_raise": "What has management said about raising money: how much, why, and what it "
    "is for?",
    "litigation": "Has management discussed this case or its possible financial impact on its "
    "calls?",
    "credit_rating": "What has management said about debt, leverage and its credit profile?",
}
DEFAULT_QUESTION = "What has management said about this on its recent calls?"


def _card_facts(filing: dict) -> str:
    """The results card's numbers, so the question is asked about the actual result."""
    for card in filing.get("cards") or []:
        if card.get("type") != "results":
            continue
        parts = [
            f"{m['label']} ₹{m['current']:,.1f} crore ({m['yoy_pct']:+.1f}% YoY)"
            for m in card["metrics"]
            if m["current"] is not None and m["yoy_pct"] is not None
        ]
        margin = card.get("margin_pct") or []
        if card.get("margin_label") and len(margin) == 3 and None not in (margin[0], margin[2]):
            parts.append(f"{card['margin_label']} {margin[0]}% against {margin[2]}% a year ago")
        return f" {card['period_label']} results: " + "; ".join(parts) + "."
    return ""


def ask_top(n: int) -> None:
    """Answer the top Push cards ahead of time, so "ask about this" opens instantly."""
    filings = json.loads((EXPORT_DIR / "filings.json").read_text(encoding="utf-8"))["filings"]
    top = sorted(
        (f for f in filings if f["group_lead"] and f["tier"] == "must_see"),
        key=lambda f: -(f["score"] or 0),
    )[:n]
    conn = connect()
    llm = LLM.from_env(conn, key_offset=9)
    answers: dict = {}
    for f in top:
        insight = f.get("insight") or {}
        context = f"{insight.get('title') or f['headline']}. {insight.get('summary') or ''}".strip()
        context += _card_facts(f)
        question = QUESTIONS.get(f["category"], DEFAULT_QUESTION)
        try:
            answers[f["id"]] = ask(conn, llm, f["symbol"], question, context)
            logging.info("asked %s %s", f["symbol"], f["category"])
        except Exception as exc:  # noqa: BLE001 - one card failing should not stop the rest
            logging.error("ask failed for %s: %s", f["id"], exc)
    out = EXPORT_DIR / "ask.json"
    out.write_text(AskAnswers(answers=answers).model_dump_json(indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--all", action="store_true", help="the research set and the portfolio")
    ap.add_argument("--refresh", action="store_true", help="re-fetch documents even if fresh")
    ap.add_argument(
        "--ask", type=int, metavar="N", help='answer "ask about this" for the top N cards'
    )
    ap.add_argument(
        "--update", type=int, metavar="N", help="rebuild up to N reports that new filings outdate"
    )
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")  # fmt: skip
    for noisy in ("httpx", "google_genai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    symbols = [s.upper() for s in args.symbols]
    if args.all:
        symbols += [c.symbol for c in RESEARCH + PORTFOLIO if c.symbol not in symbols]
    if args.ask:
        ask_top(args.ask)
    if args.update:
        print(json.dumps(update.run(connect(), OUT, args.update)))
        write_index()
    if (args.ask or args.update) and not symbols:
        return 0
    if not symbols:
        ap.error("give at least one symbol, --all, --ask N or --update N")
    failed = []
    for s in symbols:
        try:
            r = research(s, args.refresh, OUT)
            st = r.stats
            print(f"{s}: {len(r.promises)} promises, {st.graded_by_code} graded by code, "
                  f"{st.quotes_verified}/{st.claims_found} quotes verified, {st.seconds:.0f} s")  # fmt: skip
        except Exception as exc:  # noqa: BLE001 - report per company and carry on
            logging.error("%s failed: %s", s, exc)
            failed.append(s)
    write_index()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
