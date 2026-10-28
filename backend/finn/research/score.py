"""Grade promises against what was reported, in code wherever the numbers allow.

A model decides nothing that arithmetic can. For a company-wide promise in rupees about a
period that has ended, the actual comes from screener.in's tables, compiled from the
company's filed results, and the verdict is a comparison. A promise in constant currency
or dollars, such as Infosys's revenue guidance, is checked against management's own later
statement of the outcome. The rest, such as "twice the market's growth" or "operational
by Q3", goes to the model with its evidence (judge.py).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from finn.research import periods
from finn.research.extract import Call, Verified
from finn.units import crore_factor

# metric_key -> (screener line item, what to compare)
SERIES = {
    "revenue": ("Sales", "level"),
    "revenue_growth": ("Sales", "growth"),
    "pat": ("Net Profit", "level"),
    "pat_growth": ("Net Profit", "growth"),
    "ebitda_growth": ("Operating Profit", "growth"),
    "ebitda_margin": ("OPM %", "margin"),
    "ebit_margin": ("Operating Profit", "ebit"),  # less depreciation, over sales
    "working_capital_days": ("Working Capital Days", "days"),  # yearly, from the ratios table
}
RUPEE_BASIS = re.compile(r"^(inr|rs\.?|rupees?|₹|reported)$", re.I)
OPERATING_CASH = re.compile(r"operating cash|\bocf\b|cash from operations", re.I)
POSITIVE = re.compile(r"\bpositive\b", re.I)
PCT_TOLERANCE = 0.5  # screener.in rounds margins to whole percent


class Actuals:
    """screener.in's tables for one company, by statement, line item and period."""

    def __init__(self, conn: sqlite3.Connection, symbol: str, basis: str | None = None):
        """basis: consolidated or standalone; by default consolidated when there is one."""
        if basis is None:
            row = conn.execute(
                "SELECT basis FROM financials WHERE symbol = ? GROUP BY basis "
                "ORDER BY basis = 'consolidated' DESC LIMIT 1",
                (symbol,),
            ).fetchone()
            basis = row[0] if row else "consolidated"
        self.basis = basis
        self.values: dict[tuple[str, str, str], float] = {}
        self.url = None
        for st, item, period, value, url in conn.execute(
            "SELECT statement, line_item, period, value, source_url FROM financials "
            "WHERE symbol = ? AND basis = ? AND value IS NOT NULL",
            (symbol, basis),
        ):
            self.values[(st, item, period)] = value
            self.url = url
        self.latest = {
            st: max((p for (s, _, p) in self.values if s == st and p != "TTM"), default="")
            for st in ("quarters", "profit_loss", "cash_flow")
        }

    def get(self, statement: str, item: str, period: str) -> float | None:
        return self.values.get((statement, item, period))

    def has_ended(self, end: str, gran: str) -> bool:
        latest = self.latest["quarters"] if gran != "year" else self.latest["profit_loss"]
        return bool(latest) and end <= latest

    def series_value(
        self, metric_key: str, end: str, gran: str, compared_with: str | None = "year_ago"
    ) -> float | None:
        if metric_key not in SERIES or gran not in ("year", "quarter"):
            return None
        item, kind = SERIES[metric_key]
        if kind == "days":
            return self.get("ratios", item, end) if gran == "year" else None
        st = "quarters" if gran == "quarter" else "profit_loss"
        if kind == "ebit":
            op, dep, sales = (
                self.get(st, i, end) for i in ("Operating Profit", "Depreciation", "Sales")
            )
            return round((op - dep) / sales * 100, 1) if None not in (op, dep) and sales else None
        current = self.get(st, item, end)
        if kind != "growth" or current is None:
            return current
        if gran == "quarter" and compared_with is None:
            return None  # "10% growth this quarter": over a year ago or last quarter? Unknown.
        if gran == "quarter" and compared_with == "previous_period":
            y, m = int(end[:4]), int(end[5:7]) - 3
            before = self.get(st, item, f"{y - 1}-{m + 12:02d}" if m <= 0 else f"{y}-{m:02d}")
        else:  # a year's growth is always over the year before
            before = self.get(st, item, f"{int(end[:4]) - 1}{end[4:]}")
        if not before or before <= 0:
            return None
        return round((current / before - 1) * 100, 1)


@dataclass
class Grade:
    verdict: str  # beat | met | missed | pending
    actual: str | None = None
    by_outcome: Verified | None = None  # management's own later statement, when used
    outcome_call: Call | None = None


@dataclass
class Draft:
    """One promise, before the model has looked at it."""

    claim: Verified
    call: Call
    repeated_in: list[Call] = field(default_factory=list)
    grade: Grade | None = None


def _is_rupee(basis: str | None) -> bool:
    return not basis or bool(RUPEE_BASIS.match(basis.strip()))


# Words a money unit may carry. Any other word names something counted: "million units".
_MONEY_WORDS = {"inr", "rs", "rupee", "rupees", "crore", "crores", "cr", "lakh", "lakhs",
                "million", "mn", "billion", "bn", "thousand", "trillion"}  # fmt: skip
_NOT_MONEY = ("volume_growth", "working_capital_days")


def _is_money(claim) -> bool:
    """Dixon's "7 million to 7.5 million" smartphones came with no currency, and were shown
    as ₹0.7–0.75 crore. A count is not rupees, whatever its scale word."""
    if claim.metric_key in _NOT_MONEY or not _is_rupee(claim.basis):
        return False
    words = re.findall(r"[a-z]+", (claim.unit or "").lower())
    return bool(words) and all(w in _MONEY_WORDS for w in words)


def _kind(metric_key: str) -> str | None:
    return SERIES[metric_key][1] if metric_key in SERIES else None


def _target_in(claim, kind: str) -> tuple[float | None, float | None] | None:
    """The promise's low and high in the unit of the actual: crore, or percent."""
    if kind == "level":
        f = crore_factor(claim.unit)
        if not f:
            return None
        return (
            claim.low * f if claim.low is not None else None,
            claim.high * f if claim.high is not None else None,
        )
    if kind == "days":
        return (claim.low, claim.high) if claim.unit and "day" in claim.unit.lower() else None
    if claim.unit and "%" in claim.unit:
        return claim.low, claim.high
    return None


def compare(
    low: float | None, high: float | None, actual: float, tolerance: float, lower_is_better=False
) -> str:
    if lower_is_better:  # "improve to 70-85 days": above the range is the miss
        if high is not None and actual > high + tolerance:
            return "missed"
        if low is not None and actual < low - tolerance:
            return "beat"
        return "met"
    if low is not None and actual < low - tolerance:
        return "missed"
    if high is not None and actual > high + tolerance:
        return "beat"
    return "met"


def money(value: float) -> str:
    """₹3,626 crore, and −₹615 crore rather than ₹-615 crore."""
    return f"{'−' if value < 0 else ''}₹{abs(value):,.0f} crore"


def fmt_value(value: float, kind: str) -> str:
    if kind == "level":
        return money(value)
    return f"{value:.0f} days" if kind == "days" else f"{value:.1f}%"


def deadline_passed(claim, act: Actuals) -> bool | None:
    """Whether the promise's period has ended and been reported; None if it has no period."""
    p = periods.parse(claim.period)
    return act.has_ended(*p) if p else None


def target_text(claim) -> str | None:
    lo, hi, unit = claim.low, claim.high, (claim.unit or "").strip()
    if lo is None and hi is None:
        positive = claim.metric_key == "cash_flow" and POSITIVE.search(claim.statement)
        return "positive" if positive else None
    if lo == 0 and hi is None:  # "turn cash positive" arrives as at least ₹0
        return "positive"
    factor = crore_factor(unit) if _is_money(claim) else None
    if factor and factor != 1:  # "INR 40,000 million" reads as ₹4,000 crore beside a crore actual
        lo = lo * factor if lo is not None else None
        hi = hi * factor if hi is not None else None
        unit = "crore"

    def num(x: float) -> str:
        return f"{x:,.0f}" if abs(x) >= 100 else f"{x:g}"

    if unit == "%":
        body = (
            f"{num(lo)}–{num(hi)}%"
            if lo is not None and hi not in (None, lo)
            else f"{num(lo if lo is not None else hi)}%"
        )
    else:
        pre = "₹" if _is_money(claim) and crore_factor(unit) else ""
        unit_txt = re.sub(r"\b(inr|rs\.?)\b", "", unit, flags=re.I).strip()
        if lo is not None and hi not in (None, lo):
            body = f"{pre}{num(lo)}–{num(hi)} {unit_txt}"
        else:
            body = f"{pre}{num(lo if lo is not None else hi)} {unit_txt}"
    if lo is not None and hi is None:
        body = "≥ " + body
    basis = (claim.basis or "").strip()
    if basis.upper() in ("USD", "US$", "$"):  # "≥ $1,000 million", not "≥ 1,000 USD (USD)"
        body = re.sub(r"\s*\b(USD|US\$)\b", "", body)
        body = re.sub(r"(\d)", r"$\1", body, count=1)
    elif basis and not _is_rupee(basis):
        body += f" ({basis})"
    return " ".join(body.split())


def grade(d: Draft, act: Actuals, outcomes: list[tuple[Verified, Call]]) -> Grade | None:
    c = d.claim.claim
    p = periods.parse(c.period)
    if c.kind != "guidance" or c.scope != "company" or not p:
        return None
    end, gran = p

    # "Operating cash flow will be positive by March": the sign of the year's cash flow.
    if c.metric_key == "cash_flow" and gran == "year" and OPERATING_CASH.search(c.statement) \
            and POSITIVE.search(c.statement) and c.low is None:  # fmt: skip
        if not act.has_ended(end, gran):
            return Grade("pending")
        cfo = act.get("cash_flow", "Cash from Operating Activity", end)
        if cfo is None:
            return None
        return Grade("met" if cfo > 0 else "missed", money(cfo))

    kind = _kind(c.metric_key)
    if not kind:
        return None
    target = _target_in(c, kind)
    if target is None or target == (None, None):
        return None
    if not act.has_ended(end, gran):
        return Grade("pending")
    tol = PCT_TOLERANCE if kind != "level" else 0.005 * max(abs(v) for v in target if v is not None)
    lower_better = kind == "days"

    if _is_rupee(c.basis):
        actual = act.series_value(c.metric_key, end, gran, c.compared_with)
        if actual is not None:
            return Grade(compare(*target, actual, tol, lower_better), fmt_value(actual, kind))

    # Management's own later statement for the same metric, period and basis.
    for o, call in reversed(outcomes):
        oc = o.claim
        same_basis = _is_rupee(oc.basis) == _is_rupee(c.basis)
        same_comparison = oc.compared_with == c.compared_with or gran == "year"
        if oc.metric_key == c.metric_key and oc.scope == "company" and same_basis and same_comparison \
                and periods.parse(oc.period) == p and oc.low is not None:  # fmt: skip
            value = _target_in(oc, kind)
            if value and value[0] is not None:
                verdict = compare(*target, value[0], tol, lower_better)
                return Grade(verdict, fmt_value(value[0], kind), o, call)
    return None


def _same_promise(a, b) -> bool:
    keys = ("metric_key", "scope", "low", "high", "unit", "basis")
    return all(getattr(a, k) == getattr(b, k) for k in keys) and \
        periods.parse(a.period) == periods.parse(b.period)  # fmt: skip


def drafts(calls: list[Call], act: Actuals) -> list[Draft]:
    """Every guidance claim, oldest call first; a later repeat is folded into the first."""
    ordered = sorted(calls, key=lambda c: c.period)
    outcomes = [(v, call) for call in ordered for v in call.claims if v.claim.kind == "outcome"]
    out: list[Draft] = []
    for call in ordered:
        for v in call.claims:
            if v.claim.kind != "guidance":
                continue
            twin = next((d for d in out if _same_promise(d.claim.claim, v.claim)), None)
            if twin:
                twin.repeated_in.append(call)
                continue
            out.append(Draft(v, call))
    for d in out:
        d.grade = grade(d, act, outcomes)
    return out
