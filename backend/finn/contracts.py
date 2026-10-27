"""The contract between the data layer and the app.

These models define exactly what the exported JSON files contain. `export.py` validates
every file against them before writing, and writes their JSON Schema next to the data,
so the frontend can generate matching TypeScript types instead of guessing.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


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


class Filing(BaseModel):
    id: str
    symbol: str
    exchange: str
    filed_at: str
    exchange_label: str | None
    headline: str | None
    category: str | None
    tier: str | None
    classified_by: str | None
    rule: str | None
    needs_ai: bool
    text_quality: str | None
    attachment_url: str | None
    source_url: str


class AlertDefaults(BaseModel):
    price_move_pct: float
    volume_multiple: float
    volume_baseline_sessions: int


class Meta(BaseModel):
    schema_version: int = SCHEMA_VERSION
    generated_at: str
    latest_session: str | None
    filings_window_days: int
    counts: dict[str, int]
    alert_defaults: AlertDefaults
    sources: list[str]


class Portfolio(BaseModel):
    holdings: list[Holding]


class Filings(BaseModel):
    filings: list[Filing]
