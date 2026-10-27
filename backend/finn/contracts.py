"""The contract between the data layer and the app.

These models define exactly what the exported JSON files contain. `export.py` validates
every file against them before writing, and writes their JSON Schema next to the data,
so the frontend can generate matching TypeScript types instead of guessing.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 3

Tier = Literal["must_see", "glance", "routine"]


class PricePoint(BaseModel):
    date: str
    close: float
    ret_pct: float | None = Field(None, description="Close-to-close move, percent")
    vol_ratio: float | None = Field(None, description="Volume over the prior 20-session mean")
    corp_action: str | None = Field(None, description="Set when the move is a corporate action")


class Holding(BaseModel):
    symbol: str
    name: str
    sector: str | None
    size: str | None
    last_date: str | None
    close: float | None
    ret_pct: float | None
    vol_ratio: float | None
    series: list[PricePoint]
    source_url: str


# ---------------------------------------------------------------- cards


class Metric(BaseModel):
    key: str
    label: str
    current: float | None
    previous_quarter: float | None
    year_ago: float | None
    qoq_pct: float | None
    yoy_pct: float | None


class ResultsCard(BaseModel):
    """Headline numbers for one quarter versus last quarter and a year ago, in rupees crore."""

    type: Literal["results"] = "results"
    symbol: str
    period_end: str
    period_label: str = Field(description="Indian financial-year quarter, e.g. Q2 FY27")
    basis: str
    kind: Literal["standard", "bank"]
    unit: str = "₹ crore"
    metrics: list[Metric]
    margin_label: str | None = None
    margin_pct: list[float | None] = Field(
        default_factory=list, description="current, previous quarter, year ago"
    )
    source: Literal["xbrl", "filing_text", "filing_image", "screener"]
    verified: bool | None = Field(
        None, description="True when it matches screener.in, False on a mismatch"
    )
    check_note: str
    share_of_associates: float | None = Field(
        None,
        description="Reported separately from PBT in the filing; shown so the check is transparent",
    )
    source_urls: list[str]


class PersonChange(BaseModel):
    person: str
    role: str
    # "reappointment" is a renewal of someone already in the role (Dixon's MD and WTD
    # term renewals), which is not news in the way a new appointment is.
    change: Literal[
        "appointment",
        "reappointment",
        "resignation",
        "retirement",
        "cessation",
        "redesignation",
        "other",
    ]
    effective_date: str | None = None
    reason: str | None = None
    profile: str | None = Field(None, description="Bio taken from the filing's own profile section")
    previous_roles: list[str] = Field(default_factory=list)
    education: str | None = None
    profile_source: str | None = Field(
        None, description="Filing id the profile came from, if not this one"
    )


class PeopleCard(BaseModel):
    type: Literal["people"] = "people"
    changes: list[PersonChange]


class Insight(BaseModel):
    title: str
    summary: str
    why_it_matters: str | None
    sentiment: Literal["positive", "negative", "neutral", "mixed"]
    amount_inr_crore: float | None
    model: str


class PriceReaction(BaseModel):
    session: str
    ret_pct: float | None
    vol_ratio: float | None


class Filing(BaseModel):
    id: str
    symbol: str
    exchange: str
    filed_at: str
    exchange_label: str | None
    headline: str | None
    category: str | None
    tier: Tier | None
    classified_by: str | None = Field(description="rule, ai, or null when not yet sorted")
    rule: str | None
    needs_ai: bool
    text_quality: str | None
    attachment_url: str | None
    source_url: str
    insight: Insight | None = None
    events: list[str] = Field(
        default_factory=list, description="Every event in the filing, lead first"
    )
    cards: list[ResultsCard | PeopleCard] = Field(
        default_factory=list, description="On the group lead only, merged across the group"
    )
    price_reaction: PriceReaction | None = None
    score: float = Field(0, description="Priority for Today's 3: higher shows first")
    group_id: str = Field(description="Filings about the same event share a group")
    group_lead: bool = Field(
        True, description="The one filing of its group to show; the rest are attachments"
    )
    duplicate_of: str | None = Field(
        None, description="Set when this is a copy of an earlier filing's letter"
    )


# ---------------------------------------------------------------- files


class AlertDefaults(BaseModel):
    price_move_pct: float
    volume_multiple: float
    volume_baseline_sessions: int


class AIStats(BaseModel):
    calls: int
    input_tokens: int
    output_tokens: int
    by_model: dict[str, int]
    cached_answers: int


class Meta(BaseModel):
    schema_version: int = SCHEMA_VERSION
    generated_at: str
    latest_session: str | None
    filings_window_days: int
    counts: dict[str, int]
    alert_defaults: AlertDefaults
    ai: AIStats | None = None
    sources: list[str]


class Portfolio(BaseModel):
    holdings: list[Holding]


class Filings(BaseModel):
    filings: list[Filing]


# ---------------------------------------------------------------- research


class Evidence(BaseModel):
    """A sentence from a primary document, checked by code to be there, or a computed fact."""

    quote: str
    source: str = Field(description='e.g. "Q1 FY27 call, 8 Aug 2026" or "Annual report FY26"')
    page: int | None = None
    url: str


Verdict = Literal["beat", "met", "missed", "on_track", "at_risk", "pending", "unclear"]


class Promise(BaseModel):
    id: str
    metric: str
    period: str | None
    target: str | None = Field(description='e.g. "≥ ₹4,000 crore" or "1–2% (constant currency)"')
    statement: str
    said: Evidence
    repeated_in: list[str] = Field(default_factory=list, description="later calls that repeated it")
    actual: str | None = None
    actual_source: Evidence | None = None
    verdict: Verdict
    verdict_by: Literal["code", "model"]
    note: str | None = None


class CashYear(BaseModel):
    year: str
    operating_cash_flow: float | None
    net_profit: float | None
    free_cash_flow: float | None
    cash_conversion: float | None = Field(description="operating cash flow / net profit")
    debtor_days: float | None
    inventory_days: float | None
    working_capital_days: float | None


class CashQuality(BaseModel):
    applicable: bool
    reason: str | None = None
    years: list[CashYear] = Field(default_factory=list)
    conversion_5y: float | None = None
    signals: list[Evidence] = Field(default_factory=list)
    read: str | None = None


class CasePoint(BaseModel):
    point: str
    evidence: list[Evidence]


class Snapshot(BaseModel):
    about: str | None
    latest_quarter: str | None
    revenue: float | None
    revenue_yoy: float | None
    net_profit: float | None
    net_profit_yoy: float | None
    ebitda_margin: float | None


class SourceDoc(BaseModel):
    label: str
    kind: str
    url: str
    pages: int


class ResearchStats(BaseModel):
    calls_read: int
    claims_found: int
    quotes_verified: int
    quotes_dropped: int
    graded_by_code: int
    graded_by_model: int
    ai_calls: int
    cached_calls: int
    models: list[str]
    seconds: float


class ResearchReport(BaseModel):
    schema_version: int = SCHEMA_VERSION
    symbol: str
    name: str
    basis: str
    generated_at: str
    snapshot: Snapshot
    narrative: str | None
    promises: list[Promise]
    cash: CashQuality
    bull: list[CasePoint]
    bear: list[CasePoint]
    notes: list[str] = Field(default_factory=list, description="what is missing, and why")
    documents: list[SourceDoc]
    stats: ResearchStats
