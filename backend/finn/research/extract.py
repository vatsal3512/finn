"""Read each call transcript once and list what management promised and what it reported.

One Flash call per transcript, in parallel, each starting on a different key. Flash-Lite
was the plan, since this is extraction rather than judgement, but on Kaynes's February 2026
call it found 1 promise where Flash found 11, including the two that Kaynes went on to miss.
Every claim's quote is then looked up in the transcript by code, and claims whose quote is
not there are dropped and counted (decision D18).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from finn.ai.llm import LLM, AIUnavailable, Tier
from finn.research.quotes import Document
from finn.store import connect

log = logging.getLogger(__name__)

# v2: a segment target ("OSAT and PCB revenue ₹450–500 crore") must not be graded against
#     company revenue, so each claim now says whether it is company-wide.
# v3: working-capital days, which code can grade from the accounts ("70 to 85 days").
# v4: Infosys guides on operating (EBIT) margin, and v3 filed it as EBITDA margin, so code
#     compared it with the wrong line and called a met target beaten.
# v5: Asian Paints' volume growth was graded against revenue growth, and HFCL's "10% to
#     15% in this current quarter", probably over the previous quarter, against a year ago.
#     Volume growth is now its own metric, and every growth claim says what it compares with.
PROMPT_VERSION = "claims-v5"
METRICS = (
    "revenue_growth", "volume_growth", "revenue", "ebitda_margin", "ebit_margin", "ebitda_growth",
    "pat_growth", "pat",
    "working_capital_days", "order_inflow", "order_book", "capex", "debt", "cash_flow", "other",
)  # fmt: skip

SYSTEM = f"""You read one earnings-call transcript of an Indian listed company and list what
management promised and what it reported.

Two kinds of claim:
- guidance: management's own commitment about the future: growth, margins, revenue, order
  inflow, capex, debt, cash flow, capacity or a dated milestone. Include ranges, floors ("at
  least 80%"), relative targets ("twice the market's growth") and milestones ("cash
  positive by March 2027"). Not vague hopes ("we remain optimistic").
- outcome: a number management reports for a period that has ended, which a guidance could
  be checked against, such as "revenue grew 40% year on year in Q1".

Rules:
- Only what the company's management says. An analyst's question, or an analyst recalling
  earlier guidance, is not a claim.
- quote: the speaker's exact words, copied from the transcript: one sentence or less, at
  most 40 words. Do not correct, shorten inside, join or add words.
- period: the period the claim is about, written FY27, H2 FY27, Q3 FY27 or 9M FY27. The
  Indian financial year runs April to March, so FY27 is April 2026 to March 2027. Resolve
  "this year" or "by the end of the financial year" from the call's date. Null if none.
- metric_key: one of {", ".join(METRICS)}.
- revenue_growth is growth in the value of revenue or sales; growth in units, volumes or
  tonnes is volume_growth. ebitda_margin only when management says EBITDA or PBDIT;
  operating margin or EBIT margin is ebit_margin.
- compared_with, for any growth: year_ago, or previous_period when the speaker compares
  with the quarter or period just before ("sequential", "QoQ", "over last quarter"). Null
  when the speaker does not say.
- scope: company for a company-wide number; segment for a business line, product, region,
  subsidiary or plant.
- low and high: the numbers as stated. A single figure sets both; "at least" sets low only.
  unit: "%", "crore", "x market growth" and so on. basis: INR, constant currency or USD,
  when stated.
- statement: the claim in plain English, at most 20 words, with its numbers.
- At most 25 claims. Prefer company-wide numbers to segment details.
- call: what the call was, such as "Q1 FY27 earnings call" or "Investor day", with its date.
- about: what the company does, in at most 20 words, from management's own description,
  or null."""


class Claim(BaseModel):
    kind: Literal["guidance", "outcome"]
    metric_key: str
    metric: str = Field(description="short label, e.g. Revenue growth")
    scope: Literal["company", "segment"]
    period: str | None
    low: float | None = None
    high: float | None = None
    unit: str | None = None
    basis: str | None = None
    compared_with: Literal["year_ago", "previous_period"] | None = None
    statement: str
    quote: str
    speaker: str


class CallOut(BaseModel):
    call: str
    call_date: str | None = Field(None, description="YYYY-MM-DD")
    is_earnings_call: bool
    about: str | None
    claims: list[Claim]


@dataclass
class Verified:
    claim: Claim
    quote: str  # the transcript's own words
    page: int
    exact: bool


@dataclass
class Call:
    doc: Document
    period: str  # the exchange's month for the document, YYYY-MM
    call: str
    call_date: str | None
    is_earnings_call: bool
    about: str | None
    claims: list[Verified] = field(default_factory=list)
    dropped: list[Claim] = field(default_factory=list)
    model: str | None = None
    cached: bool = False


def read_call(llm: LLM, company: str, doc: Document, period: str) -> Call:
    prompt = f"Company: {company}. Filed with the exchange in {period}.\n\nTranscript:\n{doc.text}"
    out = llm.json(
        "claims", Tier.FLASH, prompt, CallOut, system=SYSTEM, version=PROMPT_VERSION,
        max_output_tokens=16384,
    )  # fmt: skip
    call = Call(doc, period, out.call, out.call_date, out.is_earnings_call, out.about,
                model=llm.last_model, cached=llm.stats["cache_hits"] > 0)  # fmt: skip
    for c in out.claims:
        m = doc.find(c.quote)
        if m:
            call.claims.append(Verified(c, m.text, m.page, m.exact))
        else:
            call.dropped.append(c)
    return call


def read_calls(
    company: str, docs: list[tuple[Document, str]], deadline: float | None = None
) -> tuple[list[Call], int]:
    """All transcripts at once, each thread with its own database connection and key order.
    Returns the calls read and how many could not be, so a report can say so."""

    def one(i: int, doc: Document, period: str) -> Call | None:
        conn = connect()
        try:
            llm = LLM.from_env(conn, key_offset=3 * i)
            llm.deadline = deadline
            return read_call(llm, company, doc, period)
        except AIUnavailable as exc:
            log.warning("could not read the %s call: %s", period, exc)
            return None
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=max(1, len(docs))) as pool:
        futures = [pool.submit(one, i, d, p) for i, (d, p) in enumerate(docs)]
        results = [f.result() for f in futures]
    calls = [c for c in results if c]
    return calls, len(results) - len(calls)
