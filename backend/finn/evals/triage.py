"""Triage against the golden set: right, grounded, useful, stable.

Four answers per filing are scored: the one shipped in the app, and three fresh runs of
the same prompt. A fresh run uses the production prompt, batching and model routing
unchanged; only the cache key differs ("triage-v7+eval-r1"), so the model really answers
again instead of the stored answer coming back.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from finn.ai.llm import LLM, AIUnavailable, Tier
from finn.config import DATA_DIR
from finn.enrich import triage
from finn.evals import checks, second
from finn.store import connect
from finn.textclean import clean

HERE = Path(__file__).parent
GOLDEN = HERE / "golden_triage.json"


def _full_text(f) -> str:
    if not f["text_path"]:
        return ""
    return " ".join(clean((DATA_DIR / f["text_path"]).read_text(encoding="utf-8")).split())


def _fresh(llm: LLM, items: dict, symbols: dict, batches, run: int) -> dict:
    """What production would store: the model's answer after code's checks on it."""
    out = {}
    for tier, ids in batches:
        prompt = "Filings:\n\n" + "\n\n".join(items[i] for i in ids)
        try:
            res = llm.json("triage", tier, prompt, triage.BatchOut, system=triage.SYSTEM,
                           version=f"{triage.PROMPT_VERSION}+eval-r{run}")  # fmt: skip
        except AIUnavailable as exc:
            print(f"  run {run}: a batch failed: {exc}")
            continue
        for it in res.items:
            if it.id in ids:
                amount = triage.amount_crore(it)
                revenue = triage.annual_revenue(llm.conn, symbols[it.id])
                out[it.id] = {"category": it.category, "tier": it.tier, "title": it.title,
                              "summary": triage.checked_shares(it.summary, amount, revenue),
                              "why": triage.checked_shares(it.why_it_matters, amount, revenue),
                              "model": llm.last_model}  # fmt: skip
    return out


def _grounding(answer: dict, ref: checks.Reference) -> dict:
    text = " ".join(filter(None, (answer["title"], answer["summary"], answer["why"])))
    # Titles are written in title case, so every word looks like a name; prose is checked.
    prose = " ".join(filter(None, (answer["summary"], answer["why"])))
    return {
        "numbers": checks.numbers(text),
        "ungrounded_numbers": ref.ungrounded_numbers(text),
        "ungrounded_names": ref.ungrounded_names(prose),
        "why_empty": not answer["why"],
        "why_repeats": checks.repeats(answer["why"], answer["summary"]),
        "why_specific": checks.specific(answer["why"]),
    }


def run(runs: int = 3, second_model: bool = True) -> dict:
    conn = connect()
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["filings"]
    ids = [g["id"] for g in golden]
    rows = {r["id"]: r for r in conn.execute(
        f"SELECT * FROM filings WHERE id IN ({','.join('?' * len(ids))})", ids)}  # fmt: skip
    items = {i: triage._item(conn, rows[i]) for i in ids}
    full = {i: _full_text(rows[i]) for i in ids}
    refs = {i: checks.Reference(items[i], full[i]) for i in ids}

    important = [i for i in ids if triage.is_important(conn, rows[i])]
    rest = [i for i in ids if i not in important]
    b = triage.BATCH
    batches = [(Tier.FLASH, important[k : k + b]) for k in range(0, len(important), b)]
    batches += [(Tier.LITE, rest[k : k + b]) for k in range(0, len(rest), b)]

    answers: dict[str, dict] = {"shipped": {}}
    for r in conn.execute(
        f"SELECT * FROM filing_insights WHERE filing_id IN ({','.join('?' * len(ids))})", ids
    ):
        answers["shipped"][r["filing_id"]] = {
            "category": r["category"], "tier": r["tier"], "title": r["title"],
            "summary": r["summary"], "why": r["why_it_matters"], "model": r["model"],
        }  # fmt: skip
    llm = LLM.from_env(conn)
    for k in range(1, runs + 1):
        print(f"triage run {k} of {runs}")
        answers[f"run{k}"] = _fresh(llm, items, {i: rows[i]["symbol"] for i in ids}, batches, k)

    per_filing = []
    for g in golden:
        i = g["id"]
        row = {"id": i, "symbol": g["symbol"], "what": g["what"],
               "accepted": {"category": g["category"], "tier": g["tier"]}, "answers": {}}  # fmt: skip
        for name, got in answers.items():
            a = got.get(i)
            if not a:
                continue
            row["answers"][name] = {
                **a,
                "category_ok": a["category"] in g["category"],
                "tier_ok": a["tier"] in g["tier"],
                **_grounding(a, refs[i]),
            }
        fresh = [
            row["answers"][f"run{k}"] for k in range(1, runs + 1) if f"run{k}" in row["answers"]
        ]
        row["stable"] = len(fresh) == runs and len({(a["category"], a["tier"]) for a in fresh}) == 1
        per_filing.append(row)

    if second_model:
        print("second-model check of the shipped answers")
        llm2 = second.checker(conn)
        for row in per_filing:
            a = row["answers"].get("shipped")
            if a:
                c = second.check_filing(llm2, items[row["id"]], full[row["id"]], a)
                row["second_model"] = c.model_dump() if c else None

    result = {"per_filing": per_filing, "summary": summarise(per_filing, list(answers)),
              "all_shipped": all_shipped(conn)}  # fmt: skip
    return result


def summarise(per_filing: list[dict], names: list[str]) -> dict:
    out = {}
    for name in names:
        got = [r["answers"][name] for r in per_filing if name in r["answers"]]
        out[name] = {
            "answered": len(got),
            "category_ok": sum(a["category_ok"] for a in got),
            "tier_ok": sum(a["tier_ok"] for a in got),
            "both_ok": sum(a["category_ok"] and a["tier_ok"] for a in got),
            "with_ungrounded_number": sum(bool(a["ungrounded_numbers"]) for a in got),
            "with_ungrounded_name": sum(bool(a["ungrounded_names"]) for a in got),
            "why_empty": sum(a["why_empty"] for a in got),
            "why_repeats": sum(a["why_repeats"] for a in got),
            "why_specific": sum(a["why_specific"] for a in got),
            "models": dict(Counter(a["model"] for a in got)),
        }
    out["stable_all_runs"] = sum(r["stable"] for r in per_filing)
    checked = [r["second_model"] for r in per_filing if r.get("second_model")]
    out["second_model"] = {
        "checked": len(checked),
        "with_unsupported": sum(bool(c["unsupported"]) for c in checked),
        "with_wrong": sum(bool(c["wrong"]) for c in checked),
        "relevant": sum(c["relevant"] for c in checked),
        "why_adds": sum(bool(c["why_adds"]) for c in checked),
        "why_present": sum(c["why_adds"] is not None for c in checked),
        "tier_fair": sum(c["tier_fair"] for c in checked),
    }
    return out


def all_shipped(conn) -> dict:
    """The code checks need no labels, so they run over every AI answer in the app."""
    rows = conn.execute(
        "SELECT f.*, i.title AS i_title, i.summary AS i_summary, i.why_it_matters AS i_why "
        "FROM filing_insights i JOIN filings f ON f.id = i.filing_id"
    ).fetchall()
    flags, n = [], 0
    for f in rows:
        n += 1
        ref = checks.Reference(triage._item(conn, f), _full_text(f))
        g = _grounding({"title": f["i_title"], "summary": f["i_summary"], "why": f["i_why"]}, ref)
        if g["ungrounded_numbers"] or g["ungrounded_names"]:
            flags.append({"id": f["id"], "symbol": f["symbol"], "numbers": g["ungrounded_numbers"],
                          "names": g["ungrounded_names"],
                          "text": " | ".join(filter(None, (f["i_title"], f["i_summary"], f["i_why"])))})  # fmt: skip
    return {"answers": n, "flagged": len(flags), "flags": flags}
