"""Research one company: the model reads, code judges.

    gather   documents and tables                    code, ~12 s for a new ticker
    cash     cash quality from the accounts          code
    claims   guidance and outcomes from each call    Flash-Lite, one call per transcript
    verify   every quote looked up in its document   code
    grade    promises against reported numbers       code
    judge    what code could not grade; bull, bear   Flash, one call, evidence checked

`stream` yields progress as each stage finishes, so the app can show cash quality within
seconds and the rest as it arrives. `research` runs it to the end and returns the report.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from finn.ai.llm import LLM, AIUnavailable, Tier
from finn.contracts import (
    CasePoint,
    Evidence,
    Guidance,
    ResearchReport,
    ResearchStats,
    Snapshot,
    SourceDoc,
)
from finn.research import cash as cashq
from finn.research import judge, periods
from finn.research.extract import Call, read_calls
from finn.research.gather import Sources, ar_excerpts, gather
from finn.research.score import Actuals, Draft, deadline_passed, drafts, target_text
from finn.store import connect, now_iso

log = logging.getLogger(__name__)

VERDICT_ORDER = ("missed", "at_risk", "beat", "met", "on_track", "pending", "unclear")
_IDS = re.compile(r"\s*\(?\b[CF]\d+(?:\s*[,/&]\s*[CF]?\d+)*\b\)?")
# Before a promise's period is over, a model may say on track or at risk, not kept or missed.
_TOO_EARLY = {"met": "on_track", "beat": "on_track", "missed": "at_risk"}
SCREENER = "screener.in, compiled from the company's filed results"


# ---------------------------------------------------------------- labels and facts


def _call_label(call: Call) -> str:
    name = call.call or ""
    when = call.period
    try:
        d = datetime.strptime(call.call_date or "", "%Y-%m-%d")
        when_txt = f"{d.day} {d:%b %Y}"
    except ValueError:
        when_txt = datetime.strptime(when, "%Y-%m").strftime("%b %Y")
    if not call.is_earnings_call or re.search(r"investor|analyst|business update", name, re.I):
        if re.search(r"\bday\b", name, re.I):
            return f"Investor day, {when_txt}"
        if re.search(r"update", name, re.I):
            return f"Business update call, {when_txt}"
        if not call.is_earnings_call:
            return f"Investor call, {when_txt}"
    m = re.search(r"\bQ([1-4])\s*(?:FY)?\s*'?(?:20)?(\d{2})\b", name, re.I)
    if m:
        return f"Q{m.group(1)} FY{m.group(2)} call, {when_txt}"
    y, mo = int(when[:4]), int(when[5:7])  # a call discusses the quarter just ended
    q, fy = {1: (3, y), 2: (3, y), 3: (3, y), 4: (4, y), 5: (4, y), 6: (4, y), 7: (1, y + 1),
             8: (1, y + 1), 9: (1, y + 1), 10: (2, y + 1), 11: (2, y + 1), 12: (2, y + 1)}[mo]  # fmt: skip
    return f"Q{q} FY{fy % 100:02d} call, {when_txt}"


def _snapshot(act: Actuals, about: str | None) -> Snapshot:
    q = act.latest["quarters"]
    if not q:
        return Snapshot(about=about, latest_quarter=None, revenue=None, revenue_yoy=None,
                        net_profit=None, net_profit_yoy=None, ebitda_margin=None)  # fmt: skip
    rev_item = "Sales" if act.get("quarters", "Sales", q) is not None else "Revenue"
    return Snapshot(
        about=about,
        latest_quarter=periods.quarter_label(q),
        revenue=act.get("quarters", rev_item, q),
        revenue_yoy=act.series_value("revenue_growth", q, "quarter")
        if rev_item == "Sales"
        else None,
        net_profit=act.get("quarters", "Net Profit", q),
        net_profit_yoy=act.series_value("pat_growth", q, "quarter"),
        ebitda_margin=act.get("quarters", "OPM %", q),
    )


class Ledger:
    """Ids for everything the judge may cite, and the evidence each id stands for."""

    def __init__(self, calls: list[Call], cash_signals: list[Evidence], snapshot: Snapshot):
        self.claims: dict[str, tuple] = {}
        self.facts: dict[str, Evidence] = {}
        n = 0
        for call in sorted(calls, key=lambda c: c.period):
            for v in call.claims:
                n += 1
                self.claims[f"C{n}"] = (v, call)
        for i, ev in enumerate(cash_signals, 1):
            self.facts[f"F{i}"] = ev
        self.snapshot = snapshot

    def id_of(self, v) -> str:
        return next(k for k, (x, _) in self.claims.items() if x is v)

    def evidence(self, ref: str) -> Evidence | None:
        if ref in self.claims:
            v, call = self.claims[ref]
            return Evidence(quote=v.quote, source=call.doc.label, page=v.page, url=call.doc.url)
        return self.facts.get(ref)


def _judge_prompt(src: Sources, ledger: Ledger, ds: list[Draft], excerpts) -> str:
    lines = [f"Company: {src.name}" + (f" ({src.sector})" if src.sector else ""), ""]
    s = ledger.snapshot
    if s.latest_quarter:
        lines.append(f"Latest quarter {s.latest_quarter} (screener.in): revenue ₹{s.revenue or 0:,.0f} crore"
                     f" ({s.revenue_yoy:+.1f}% YoY), net profit ₹{s.net_profit or 0:,.0f} crore"
                     f" ({(s.net_profit_yoy or 0):+.1f}% YoY), EBITDA margin {s.ebitda_margin}%."
                     if s.revenue_yoy is not None else f"Latest quarter {s.latest_quarter}.")  # fmt: skip
    lines += ["", "Claims (id | call | kind | statement | quote):"]
    for cid, (v, call) in ledger.claims.items():
        c = v.claim
        lines.append(
            f'{cid} | {call.doc.label} | {c.kind}, {c.scope} | {c.statement} | "{v.quote}"'
        )
    graded = [d for d in ds if d.grade]
    lines += ["", "Graded by code (do not change these verdicts):"]
    for d in graded:
        g = d.grade
        actual = f"; reported {g.actual}" if g.actual else ""
        lines.append(f"{ledger.id_of(d.claim)}: {g.verdict}{actual}")
    lines += ["", "To rule on:"]
    lines.append(", ".join(ledger.id_of(d.claim) for d in ds if not d.grade) or "(none)")
    lines += ["", "Facts computed from the filed accounts:"]
    lines += [f"{fid}: {ev.quote}" for fid, ev in ledger.facts.items()] or ["(none)"]
    if excerpts:
        lines += ["", f"Annual report {src.ar_period} excerpts:"]
        for section, page, text in excerpts:
            lines.append(f"[{section}, page {page}]\n{text[:3500]}")
    return "\n".join(lines)


_RUPEES = (
    (re.compile(r"\bnegative (?:INR |Rs\.? ?|₹)?([\d,.]+) crores? rupees\b", re.I), r"−₹\1 crore"),
    (re.compile(r"\b([\d,.]+) crores? rupees\b", re.I), r"₹\1 crore"),
    (re.compile(r"\b(?:INR|Rs\.?) ?([\d,.]+) ?crores?\b", re.I), r"₹\1 crore"),
    (re.compile(r"\bnegative ₹([\d,.]+)"), r"−₹\1"),
    (re.compile(r"(?<![₹\d,.])(\d[\d,.]*) crores?\b"), r"₹\1 crore"),  # "14,553 crore"
)


def _prose(text: str | None) -> str | None:
    """Ids belong in evidence lists: 'grew 40% (C31)' becomes 'grew 40%'. Amounts read as
    the app writes them: '600 crore rupees' and 'INR 3,626 crores' become ₹600 crore."""
    if not text:
        return None
    text = " ".join(_IDS.sub("", text).split())
    for rx, repl in _RUPEES:
        text = rx.sub(repl, text)
    return text


def model_verdict(ruling, cid: str, claim, act: Actuals) -> tuple[str, list[str], str | None]:
    """The judge's verdict on a promise code could not grade, held to three rules:
    a promise is not evidence for itself; until its period ends, or if it has none, it can
    only be on track or at risk; once the period is over, it was kept, missed or is unclear,
    and a later period's number does not make it "on track"."""
    if not ruling or not ruling.verdict:
        return "unclear", [], None
    others = [r for r in ruling.evidence if r != cid]
    verdict = ruling.verdict
    if not others and verdict not in ("pending", "unclear"):
        verdict = "pending"
    ended = deadline_passed(claim, act)
    if not ended:  # still running, or open-ended ("margins of about 11%")
        verdict = _TOO_EARLY.get(verdict, verdict)
    elif verdict in ("pending", "on_track", "at_risk"):
        verdict = "unclear"
    # "Applies to the full financial year" says nothing; a note must carry a finding.
    note = _prose(ruling.note) if verdict not in ("pending", "unclear") else None
    return verdict, others, note


def _points(points, ledger: Ledger, src: Sources) -> tuple[list[CasePoint], int]:
    out, dropped = [], 0
    for p in points[:3]:
        evidence = [e for e in (ledger.evidence(r) for r in p.evidence) if e]
        if p.ar_quote:
            m = src.annual_report.find(p.ar_quote) if src.annual_report else None
            if not m:  # the point named its source, and the source does not say it
                dropped += 1
                continue
            evidence.insert(0, Evidence(quote=m.text, source=src.annual_report.label,
                                        page=m.page, url=src.annual_report.url))  # fmt: skip
        if evidence:
            out.append(CasePoint(point=_prose(p.point), evidence=evidence))
        else:
            dropped += 1
    return out, dropped


def _row(i: int, d: Draft, ruling, ledger: Ledger, act: Actuals) -> Guidance:
    """One promise as the app shows it: what was said, what was delivered, and who judged."""
    cid = ledger.id_of(d.claim)
    c, call = d.claim.claim, d.call
    said = Evidence(quote=d.claim.quote, source=call.doc.label, page=d.claim.page, url=call.doc.url)
    actual_src = None
    if d.grade and d.grade.by_outcome:
        o = d.grade.by_outcome
        actual_src = Evidence(quote=o.quote, source=d.grade.outcome_call.doc.label, page=o.page,
                              url=d.grade.outcome_call.doc.url)  # fmt: skip
    elif d.grade and d.grade.actual:
        actual_src = Evidence(quote=f"{c.metric}, {c.period}: {d.grade.actual}", source=SCREENER,
                              url=act.url or "")  # fmt: skip
    if d.grade:  # code's verdict stands; the judge may only add a note, such as a cut
        verdict = d.grade.verdict
        note = _prose(ruling.note) if ruling else None
    else:
        verdict, others, note = model_verdict(ruling, cid, c, act)
        if others:
            actual_src = next((e for e in map(ledger.evidence, others) if e), None)
    return Guidance(
        id=f"P{i}", metric=c.metric, period=c.period, target=target_text(c), statement=c.statement,
        said=said, repeated_in=[r.doc.label for r in d.repeated_in],
        actual=d.grade.actual if d.grade else None, actual_source=actual_src, verdict=verdict,
        verdict_by="code" if d.grade else "model", note=note,
    )  # fmt: skip


# ---------------------------------------------------------------- the pipeline


def stream(
    symbol: str, refresh: bool = False, save_dir: Path | None = None, budget_s: float | None = None
) -> Iterator[dict]:
    """budget_s caps the time spent waiting on models, for a live request. Past it, no new
    model call starts, and the report says what it could not finish."""
    t0 = time.perf_counter()
    deadline = time.monotonic() + budget_s if budget_s else None
    conn = connect()
    symbol = symbol.upper()
    yield {
        "stage": "gather",
        "message": f"Collecting {symbol}'s call transcripts and annual report",
    }
    src = gather(conn, symbol, refresh)
    act = Actuals(conn, symbol, src.basis)
    parent = Actuals(conn, symbol, "standalone") if src.basis == "consolidated" else None
    if not src.transcripts:
        # No calls means no promises to check, but the accounts still say whether profit
        # turns into cash. A partial report beats a dead end.
        src.notes.insert(0, f"{src.name} has not published earnings-call transcripts, so there are "
                            "no management promises to check. The numbers below are from its accounts.")  # fmt: skip
        cash = cashq.compute(act, src.is_bank, parent)
        report = ResearchReport(
            symbol=symbol, name=src.name, basis=src.basis, generated_at=now_iso(),
            snapshot=_snapshot(act, None), narrative=None, promises=[], cash=cash, bull=[], bear=[],
            notes=src.notes, documents=[],
            stats=ResearchStats(calls_read=0, claims_found=0, quotes_verified=0, quotes_dropped=0,
                                graded_by_code=0, graded_by_model=0, ai_calls=0, cached_calls=0,
                                models=[], seconds=round(time.perf_counter() - t0, 1)),
        )  # fmt: skip
        if save_dir:
            save_dir.mkdir(parents=True, exist_ok=True)
            (save_dir / f"{symbol}.json").write_text(
                report.model_dump_json(indent=1), encoding="utf-8"
            )
        yield {"stage": "done", "message": "Done: accounts only", "notes": src.notes,
               "report": report.model_dump()}  # fmt: skip
        return
    cash = cashq.compute(act, src.is_bank, parent)
    yield {"stage": "cash", "message": f"{len(src.transcripts)} calls and "
           f"{'an annual report' if src.annual_report else 'no annual report'} found",
           "cash": cash.model_dump(), "snapshot": _snapshot(act, None).model_dump()}  # fmt: skip

    calls, unread = read_calls(src.name, src.transcripts, deadline)
    if unread:
        src.notes.append(f"{unread} of {len(src.transcripts)} calls could not be read in time.")
    if not calls:
        yield {"stage": "error", "message": "The AI models are too busy to read the calls right "
               "now. Try again in a few minutes."}  # fmt: skip
        return
    for call in calls:
        call.doc.label = _call_label(call)
    n_claims = sum(len(c.claims) + len(c.dropped) for c in calls)
    n_ok = sum(len(c.claims) for c in calls)
    yield {"stage": "claims", "message": f"Read {len(calls)} calls: {n_ok} of {n_claims} quotes "
           "found in the transcripts"}  # fmt: skip

    ds = drafts(calls, act)
    latest = max(calls, key=lambda c: c.period)
    snapshot = _snapshot(act, latest.about)
    if snapshot.latest_quarter and not any(snapshot.latest_quarter in c.doc.label for c in calls):
        src.notes.append(f"{snapshot.latest_quarter} results are out, but that quarter's call "
                         "transcript is not filed yet, so its guidance is not here.")  # fmt: skip
    ledger = Ledger(calls, cash.signals, snapshot)
    # Code's verdicts are final, so the app can show them while the judge works.
    settled = [_row(i, d, None, ledger, act) for i, d in enumerate(ds, 1) if d.grade]
    yield {"stage": "graded", "message": f"{len(settled)} of {len(ds)} promises graded against "
           "reported numbers", "snapshot": snapshot.model_dump(),
           "promises": [g.model_dump() for g in settled], "total": len(ds)}  # fmt: skip

    judged, j_calls, j_cached, models = None, 0, 0, {c.model for c in calls if c.model}
    try:
        llm = LLM.from_env(conn, key_offset=7)
        llm.deadline = deadline
        llm.patient = deadline is None
        tier = Tier.REASON if deadline is None else Tier.FLASH  # someone is waiting live
        judged = judge.run(llm, _judge_prompt(src, ledger, ds, ar_excerpts(src)), tier)
        j_calls, j_cached = 1, llm.stats["cache_hits"]
        models.add(llm.last_model)
    except AIUnavailable as exc:
        log.warning("judge unavailable for %s: %s", symbol, exc)
        src.notes.append(
            "The reasoning model was unavailable: ungraded promises are marked unclear."
        )

    rulings = {r.id: r for r in (judged.rulings if judged else [])}
    promises = [
        _row(i, d, rulings.get(ledger.id_of(d.claim)), ledger, act) for i, d in enumerate(ds, 1)
    ]
    promises.sort(key=lambda p: (VERDICT_ORDER.index(p.verdict), p.period or ""))

    bull, bear, dropped_points = [], [], 0
    if judged:
        bull, n1 = _points(judged.bull, ledger, src)
        bear, n2 = _points(judged.bear, ledger, src)
        dropped_points = n1 + n2
        cash.read = _prose(judged.cash_read) if cash.applicable else None

    report = ResearchReport(
        symbol=symbol, name=src.name, basis=src.basis, generated_at=now_iso(), snapshot=snapshot,
        narrative=_prose(judged.narrative) if judged else None, promises=promises, cash=cash,
        bull=bull, bear=bear,
        notes=src.notes,
        documents=[SourceDoc(label=d.label, kind="transcript", url=d.url, pages=len(d.pages))
                   for d, _ in src.transcripts]
        + ([SourceDoc(label=src.annual_report.label, kind="annual_report", url=src.annual_report.url,
                      pages=len(src.annual_report.pages))] if src.annual_report else []),
        stats=ResearchStats(
            calls_read=len(calls), claims_found=n_claims, quotes_verified=n_ok,
            quotes_dropped=n_claims - n_ok, graded_by_code=sum(1 for d in ds if d.grade),
            graded_by_model=sum(
                1 for p in promises if p.verdict_by == "model" and p.verdict not in ("pending", "unclear")
            ),
            ai_calls=len(calls) + j_calls, cached_calls=sum(c.cached for c in calls) + j_cached,
            models=sorted(m for m in models if m), seconds=round(time.perf_counter() - t0, 1),
        ),
    )  # fmt: skip
    if dropped_points:
        log.info(
            "%s: %d bull/bear points dropped for lack of checked evidence", symbol, dropped_points
        )
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
        (save_dir / f"{symbol}.json").write_text(report.model_dump_json(indent=1), encoding="utf-8")
    yield {"stage": "done", "message": f"Done in {report.stats.seconds:.0f} s", "notes": src.notes,
           "report": report.model_dump()}  # fmt: skip


def research(symbol: str, refresh: bool = False, save_dir: Path | None = None) -> ResearchReport:
    last = None
    for event in stream(symbol, refresh, save_dir):
        log.info("%s %s: %s", symbol, event["stage"], event.get("message", ""))
        last = event
    if not last or last["stage"] != "done":
        raise RuntimeError(last["message"] if last else f"research failed for {symbol}")
    return ResearchReport.model_validate(last["report"])
