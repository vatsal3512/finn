"""Rule-based first pass over exchange filings.

Why rules before AI: on 601 real filings from October 2026, simple patterns on the
exchange's own subject line settled 41% of them (trading-window notices, newspaper ads,
employee share allotments and so on) with no model call at all. Rules are free, instant
and auditable; the `rule` column records which one fired.

A rule gives a category from the reference document and a default tier. It can also ask
for the AI step:
- needs_ai = False: routine and fully understood. Nothing else happens to it.
- needs_ai = True with a category: the category is certain, but a summary is wanted, or
  the tier depends on details only the document holds (an upgrade vs a downgrade).
- category None: the subject line is too vague ("General Updates"), so the AI classifies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CATEGORIES = (
    "results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading",
    "earnings_call", "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex",
    "press_release", "postal_ballot", "agm_egm", "pledging", "unclassified",
)  # fmt: skip

TIERS = ("must_see", "glance", "routine")

DEFAULT_TIER = {
    "results": "must_see",
    "M&A": "must_see",
    "fund_raise": "must_see",
    "management_change": "must_see",
    "litigation": "must_see",
    "pledging": "must_see",
    "credit_rating": "glance",
    "insider_trading": "glance",
    "dividend": "glance",
    "bonus_split": "glance",
    "capex": "glance",
    "press_release": "glance",
    "earnings_call": "routine",
    "investor_meetings": "routine",
    "postal_ballot": "routine",
    "agm_egm": "routine",
    "unclassified": "routine",
}


@dataclass(frozen=True)
class Verdict:
    category: str | None
    tier: str | None
    needs_ai: bool
    rule: str


@dataclass(frozen=True)
class Rule:
    name: str
    label: str  # regex on the exchange's subject line
    category: str | None
    text: str | None = None  # optional regex that must also match the headline text
    tier: str | None = None  # overrides the category default
    needs_ai: bool | None = None  # None means: routine tier -> False, otherwise True


def _rx(p: str | None) -> re.Pattern | None:
    return re.compile(p, re.I) if p else None


# Order matters: the first matching rule wins. Routine paperwork comes first so that, for
# example, "Trading Window" never falls through to the insider-trading rule.
RULES: tuple[Rule, ...] = (
    # Routine paperwork, settled without AI
    Rule("trading_window", r"trading window", "unclassified"),
    Rule("newspaper", r"newspaper", "unclassified"),
    Rule("depository_cert", r"certificate under sebi|reg(ulation)?\.? ?74", "unclassified"),
    Rule("employee_stock", r"esop|esos|esps|options to purchase", "unclassified"),
    Rule("esop_in_text", r".", "unclassified", text=r"stock option|esop|esos|employee stock"),
    Rule("share_certificate", r"loss of share|duplicate share|issue of duplicate", "unclassified"),
    Rule("investor_complaints", r"investor complaint|grievance", "unclassified"),
    Rule("shareholding", r"shareholding pattern", "unclassified"),
    Rule("monitoring_agency", r"monitoring agency", "unclassified"),
    Rule("esg", r".", "unclassified", text=r"\besg\b|brsr|sustainability report"),
    Rule("compliance", r"compliance|statement of deviation|change in address|registrar", "unclassified"),
    Rule("auditor", r".", "unclassified", text=r"statutory auditor|secretarial auditor|cost auditor"),
    Rule("iepf", r".", "unclassified", text=r"investor education and protection|\biepf\b"),
    Rule("pit_code", r".", "unclassified", text=r"regulation 8\(?2\)?|code of practices and procedures for fair disclosure"),
    Rule("capital_admin", r"authori[sz]ed capital|amendment to (aoa|moa)|memorandum|articles of association", "unclassified"),
    Rule("board_meeting_notice", r"board meeting intimation|intimation of board meeting", "results", tier="routine"),
    # Calls and meetings
    Rule("call_material", r"analysts?\s*/\s*(institutional )?investor meet|con\. ?call|earnings call", "earnings_call",
         text=r"transcript|recording|audio|conference call|earnings call|con\. ?call"),
    Rule("investor_meet", r"analysts?\s*/\s*(institutional )?investor meet|investor meet", "investor_meetings"),
    Rule("analyst_meet_text", r".", "investor_meetings", text=r"analyst\(?s\)?/investor\(?s\)? meet"),
    Rule("postal_ballot", r"postal ballot|shareholders meeting", "postal_ballot", text=r"postal ballot"),
    Rule("agm_egm", r"shareholders meeting|general meeting|\bagm\b|\begm\b", "agm_egm"),
    # Results
    Rule("results", r"financial result|outcome of board meeting|results", "results",
         text=r"financial results?|unaudited|audited .*results|quarter(ly)? .*results"),
    Rule("results_text", r".", "results", text=r"(unaudited|audited) .{0,60}financial results"),
    Rule("investor_presentation", r"investor presentation|earnings presentation", "results", tier="glance"),
    # Pledges and insider dealings
    Rule("pledge", r"pledge|encumbrance", "pledging"),
    Rule("pledge_text", r".", "pledging", text=r"\bpledg|encumbrance"),
    Rule("insider", r"insider trading|substantial acquisition|\bsast\b|regulation 7\(?2\)?|reg\. ?29|reg\. ?31", "insider_trading"),
    # Capital raising, including routine debt paper
    Rule("debt_paper", r".", "fund_raise", tier="routine",
         text=r"non[- ]?convertible debenture|\bncds?\b|commercial paper"),
    Rule("equity_raise", r"qualified institution|\bqip\b|rights issue|preferential|issue of securities|buy ?back|allotment of securities", "fund_raise"),
    Rule("equity_raise_text", r".", "fund_raise",
         text=r"rights issue|qualified institution|preferential (issue|allotment)|buy-?back of"),
    # Deals
    Rule("subsidiary_setup", r"acquisition|investment", "M&A", tier="glance",
         text=r"incorporation of|wholly[- ]owned subsidiary|additional investment|infusion"),
    Rule("deal", r"acquisition|amalgamation|merger|demerger|scheme of arrangement|sale or disposal|joint venture|slump sale", "M&A"),
    # People
    Rule("independent_director", r"director|appointment|cessation|resignation|management", "management_change",
         tier="glance", text=r"independent director|non[- ]executive|senior management personnel|\bsmp\b"),
    Rule("management", r"change in management|change in director|resignation|appointment|cessation|re-?appointment|kmp", "management_change"),
    # Disputes and regulators
    Rule("litigation", r"litigation|action\(s\) (taken|initiated)|orders passed|insolvency|fraud|default|penalty|show cause", "litigation"),
    # Ratings and payouts. Rating direction is in the document, so the AI sets the tier.
    Rule("credit_rating", r"credit rating", "credit_rating"),
    Rule("bonus_split", r"bonus|split|sub-?division", "bonus_split"),
    Rule("dividend", r"dividend", "dividend"),
    Rule("record_date", r"record date", None),  # the purpose is only in the text
    # Business news
    Rule("orders", r"bagging|receiving of orders|order win", "press_release"),
    Rule("capex", r".", "capex", text=r"commercial operation|commercial production|capacity expansion|new plant|greenfield|brownfield"),
    Rule("monthly_update", r".", "press_release", tier="glance",
         text=r"monthly business|production volume|production,? sales|sales figures|\bsiam\b|production and off-?take"),
    Rule("clarification", r"rumou?r|news verification|clarification|price movement", "press_release"),
)  # fmt: skip

_COMPILED = [(r, _rx(r.label), _rx(r.text)) for r in RULES]


def classify(exchange_label: str | None, headline: str | None) -> Verdict:
    label = exchange_label or ""
    text = f"{label} {headline or ''}"
    for rule, label_rx, text_rx in _COMPILED:
        if label_rx and not label_rx.search(label):
            continue
        if text_rx and not text_rx.search(text):
            continue
        if rule.category is None:
            return Verdict(None, None, True, rule.name)
        tier = rule.tier or DEFAULT_TIER[rule.category]
        needs_ai = rule.needs_ai if rule.needs_ai is not None else tier != "routine"
        return Verdict(rule.category, tier, needs_ai, rule.name)
    return Verdict(None, None, True, "no_rule")
