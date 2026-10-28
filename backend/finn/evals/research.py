"""Every shipped research report and "Was this expected?" answer, checked for grounding.

Code checks, over all of them:
- each quote is found again in the source document it names, at the page it names;
- each number in a promise, a bull or bear point, or the one-line read is graded:
    in_quote      in the quotes it cites, or in the figures code computed from the accounts
    converted     the same, in another unit ("₹713.2 crore" from "INR 7,132 million")
    in_documents  not in what it cites, but in the company's own documents: true, loosely cited
    nowhere       in none of them: a possible invention, read by a person
- no point cites the same quote twice.
Then the second model reads each claim with its quotes and says yes, partly or no.
"""

from __future__ import annotations

import json
from collections import Counter

from finn import grounding as checks
from finn.config import DATA_DIR, EXPORT_DIR
from finn.evals import second
from finn.pdftext import load_pages
from finn.research.quotes import Document
from finn.store import connect

REPORTS = EXPORT_DIR / "research"


class Docs:
    """Source documents by URL, loaded once."""

    def __init__(self, conn):
        self.conn, self.cache = conn, {}

    def get(self, url: str) -> Document | None:
        if url not in self.cache:
            row = self.conn.execute(
                "SELECT text_path FROM documents WHERE url = ? AND text_path IS NOT NULL", (url,)
            ).fetchone()
            self.cache[url] = Document("", url, load_pages(DATA_DIR / row[0])) if row else None
        return self.cache[url]


def _quote_check(docs: Docs, ev: dict) -> str:
    """found (right page), wrong_page, missing, no_source, or computed: a line code wrote
    from the accounts, such as a cash-flow signal, which is not a quote."""
    if "screener.in" in ev["url"]:
        return "computed"
    doc = docs.get(ev["url"])
    if doc is None:
        return "no_source"
    m = doc.find(ev["quote"])
    if m is None:
        return "missing"
    return "found" if ev.get("page") in (None, m.page) else "wrong_page"


def _figures(r: dict) -> str:
    """What code computed: the snapshot, the cash table, each promise's actual. Not the
    targets: a model wrote those, so they are what is being checked."""
    return json.dumps({
        "snapshot": r.get("snapshot"), "cash": r.get("cash"),
        "actuals": [{k: p.get(k) for k in ("metric", "period", "actual")}
                    for p in r.get("promises", [])],
    }, ensure_ascii=False)  # fmt: skip


class Grader:
    """Grades every number in a piece of text, and keeps the ones a person should read."""

    def __init__(self):
        self.counts: Counter[str] = Counter()
        self.flags: list[dict] = []

    def grade(self, where: str, text: str, cited: checks.Reference, wider: checks.Reference):
        out: dict[str, list[str]] = {}
        for t in checks.numbers(text):
            if cited.has_number(t):
                g = "in_quote"
            elif cited.is_converted(t):
                g = "converted"
            elif wider.has_number(t) or wider.is_converted(t):
                g = "in_documents"
            else:
                g = "nowhere"
            self.counts[g] += 1
            if g != "in_quote":
                out.setdefault(g, []).append(t)
        if out:
            self.flags.append({"where": where, **out, "text": text})


def check_report(docs: Docs, r: dict, grader: Grader) -> dict:
    quotes, items, dupes = [], [], []
    figures = _figures(r)
    sources = [docs.get(d["url"]) for d in r.get("documents") or []]
    wider = checks.Reference(figures, *(d.text for d in sources if d))
    sym = r["symbol"]
    for p in r.get("promises", []):
        quotes.append(_quote_check(docs, p["said"]))
        # The target is the model's reading of the quote, so it is checked, not trusted.
        cited = checks.Reference(p["said"]["quote"])
        grader.grade(
            f"{sym} promise {p['id']}", f"{p['statement']} {p.get('target') or ''}", cited, wider
        )
        items.append({"id": f"{sym}:{p['id']}", "claim": f"{p['statement']} (target: {p.get('target')})",
                      "quotes": [p["said"]["quote"]]})  # fmt: skip
    for side in ("bull", "bear"):
        for n, pt in enumerate(r.get(side) or [], 1):
            evs = pt.get("evidence") or []
            quotes += [_quote_check(docs, e) for e in evs]
            qs = [e["quote"] for e in evs]
            if len(set(qs)) < len(qs):
                dupes.append(f"{sym} {side} {n}")
            grader.grade(f"{sym} {side} {n}", pt["point"], checks.Reference(*qs, figures), wider)
            items.append({"id": f"{sym}:{side}{n}", "claim": pt["point"], "quotes": qs,
                          "figures": figures if checks.numbers(pt["point"]) else None})  # fmt: skip
    every = [p["said"]["quote"] for p in r.get("promises", [])] + [
        e["quote"]
        for s in ("bull", "bear")
        for pt in r.get(s) or []
        for e in pt.get("evidence") or []
    ]
    grader.grade(
        f"{sym} narrative", r.get("narrative") or "", checks.Reference(figures, *every), wider
    )
    return {"quotes": quotes, "items": items, "dupes": dupes}


def check_answers(docs: Docs, grader: Grader) -> dict:
    answers = json.loads((EXPORT_DIR / "ask.json").read_text(encoding="utf-8"))["answers"]
    filings = json.loads((EXPORT_DIR / "filings.json").read_text(encoding="utf-8"))
    by_id = {f["id"]: f for f in filings["filings"]}
    quotes, items = [], []
    for n, (filing_id, a) in enumerate(answers.items(), 1):
        evs = a.get("evidence") or []
        quotes += [_quote_check(docs, e) for e in evs]
        # The answer may also use the Push card it was asked from: its numbers and summary.
        card = json.dumps(by_id.get(filing_id), ensure_ascii=False)
        qs = [e["quote"] for e in evs]
        cited = checks.Reference(*qs, card, " ".join(a.get("calls") or []))
        wider = checks.Reference(card, *(d.text for d in (docs.get(e["url"]) for e in evs) if d))
        grader.grade(f"ask {a['symbol']}", a["answer"], cited, wider)
        items.append({"id": f"ask{n}:{a['symbol']}", "claim": a["answer"], "quotes": qs,
                      "figures": f"calls read: {', '.join(a.get('calls') or [])}"})  # fmt: skip
    return {"answers": len(answers), "quotes": quotes, "items": items}


def run(second_model: bool = True) -> dict:
    conn = connect()
    docs = Docs(conn)
    grader = Grader()
    files = [f for f in sorted(REPORTS.glob("*.json")) if f.name != "index.json"]
    reports = [check_report(docs, json.loads(f.read_text(encoding="utf-8")), grader) for f in files]
    ask = check_answers(docs, grader)
    all_quotes = Counter(q for r in reports + [ask] for q in r["quotes"])
    result = {
        "reports": len(reports),
        "answers": ask["answers"],
        "quotes": {
            k: all_quotes[k] for k in ("found", "wrong_page", "missing", "no_source", "computed")
        },
        "numbers": dict(grader.counts),
        "duplicate_quotes": [d for r in reports for d in r["dupes"]],
        "number_flags": grader.flags,
    }
    if second_model:
        llm2 = second.checker(conn)
        verdicts = []
        for f, r in zip(files + ["ask"], reports + [ask], strict=True):
            print(f"second-model check: {getattr(f, 'stem', f)}")
            verdicts += [c.model_dump() for c in second.check_quoted(llm2, r["items"])]
        result["second_model"] = {
            "claims": sum(len(r["items"]) for r in reports + [ask]),
            "checked": len(verdicts),
            **{k: sum(v["supported"] == k for v in verdicts) for k in ("yes", "partly", "no")},
            "not_yes": [v for v in verdicts if v["supported"] != "yes"],
        }
    return result
