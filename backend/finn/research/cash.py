"""Cash quality: do profits turn into cash? Computed entirely in code, no model.

Five years of operating cash flow against net profit, free cash flow, and the working-
capital days that explain a gap. The facts are stated as plain sentences with their
numbers; the model only adds one line of reading on top (judge.py).

Banks are skipped: a bank's operating cash flow swings with deposits and loans, so
"cash conversion" says nothing about the quality of its earnings.
"""

from __future__ import annotations

from finn.contracts import CashQuality, CashYear, Evidence
from finn.research import periods
from finn.research.score import Actuals, money

YEARS = 5
SOURCE = "Computed from screener.in's cash-flow statement and ratios"


def _r(x: float | None, digits: int = 2) -> float | None:
    return round(x, digits) if x is not None else None


GAP = 0.4  # conversion points between group and parent that are worth saying


def _conversion(act: Actuals, ends: list[str]) -> float | None:
    cfo = [act.get("cash_flow", "Cash from Operating Activity", e) for e in ends]
    pat = [act.get("profit_loss", "Net Profit", e) for e in ends]
    pairs = [(c, p) for c, p in zip(cfo, pat, strict=True) if c is not None and p is not None]
    total = sum(p for _, p in pairs)
    return _r(sum(c for c, _ in pairs) / total) if pairs and total > 0 else None


def compute(act: Actuals, is_bank: bool, parent: Actuals | None = None) -> CashQuality:
    if is_bank:
        return CashQuality(
            applicable=False,
            reason="Not meaningful for a bank: its operating cash flow moves with deposits and loans.",
        )
    ends = sorted({p for (st, _, p) in act.values if st == "cash_flow" and p != "TTM"})[-YEARS:]
    years = []
    for end in ends:
        cfo = act.get("cash_flow", "Cash from Operating Activity", end)
        pat = act.get("profit_loss", "Net Profit", end)
        years.append(
            CashYear(
                year=periods.year_label(end),
                operating_cash_flow=cfo,
                net_profit=pat,
                free_cash_flow=act.get("cash_flow", "Free Cash Flow", end),
                cash_conversion=_r(cfo / pat) if cfo is not None and pat and pat > 0 else None,
                debtor_days=act.get("ratios", "Debtor Days", end),
                inventory_days=act.get("ratios", "Inventory Days", end),
                working_capital_days=act.get("ratios", "Working Capital Days", end),
            )
        )
    if not years:
        return CashQuality(
            applicable=False, reason="screener.in has no cash-flow statement for it."
        )

    pairs = [(y.operating_cash_flow, y.net_profit) for y in years
             if y.operating_cash_flow is not None and y.net_profit is not None]  # fmt: skip
    total_cfo, total_pat = sum(c for c, _ in pairs), sum(p for _, p in pairs)
    conversion = _r(total_cfo / total_pat) if pairs and total_pat > 0 else None
    span = f"{years[0].year}–{years[-1].year}"
    signals: list[str] = []

    if conversion is not None:
        if conversion < 0:
            signals.append(f"Over {span}, operating cash flow totalled {money(total_cfo)} "
                           f"against {money(total_pat)} of reported profit.")  # fmt: skip
        elif conversion < 0.7:
            signals.append(f"Over {span}, only {conversion:.0%} of reported profit arrived as "
                           f"operating cash (₹{total_cfo:,.0f} of ₹{total_pat:,.0f} crore).")  # fmt: skip
        elif conversion >= 1:
            signals.append(f"Over {span}, operating cash flow of ₹{total_cfo:,.0f} crore covered "
                           f"all of reported profit, ₹{total_pat:,.0f} crore.")  # fmt: skip
    negative = [y.year for y in years if (y.operating_cash_flow or 0) < 0 < (y.net_profit or 0)]
    if negative:
        signals.append(f"Operating cash flow was negative in {', '.join(negative)} while "
                       f"reported profit was positive.")  # fmt: skip
    fcf = [y.free_cash_flow for y in years if y.free_cash_flow is not None]
    if fcf and sum(fcf) < 0:
        n = sum(1 for x in fcf if x < 0)
        signals.append(f"Free cash flow was negative in {n} of {len(fcf)} years, "
                       f"{money(sum(fcf))} in total.")  # fmt: skip
    for label, attr in (("debtor days", "debtor_days"), ("inventory days", "inventory_days")):
        series = [(y.year, getattr(y, attr)) for y in years if getattr(y, attr) is not None]
        if len(series) >= 3:
            (y0, v0), (y1, v1) = series[-3], series[-1]
            if v0 > 0 and v1 >= v0 * 1.3 and v1 - v0 >= 15:
                signals.append(f"{label.capitalize()} rose from {v0:.0f} to {v1:.0f} between "
                               f"{y0} and {y1}: cash is waiting longer in the business.")  # fmt: skip

    own = _conversion(parent, ends) if parent else None
    if own is not None and conversion is not None and own - conversion >= GAP and own >= 0.8:
        # Said first: it changes how every other number here should be read.
        signals.insert(0, f"The parent company alone turned {own:.0%} of its profit into operating "
                          f"cash over {span}; the shortfall sits in its subsidiaries.")  # fmt: skip
    else:
        own = None

    url = act.url or ""
    return CashQuality(
        applicable=True,
        years=years,
        conversion_5y=conversion,
        parent_conversion_5y=own,
        signals=[Evidence(quote=s, source=SOURCE, url=url) for s in signals],
    )
