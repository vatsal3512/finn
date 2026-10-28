"""The one reasoning call: rule on what code could not, and make the bull and bear case.

It runs on the REASON tier (Flash with high thinking) because it compares and judges. It
sees only what FINN extracted and checked: claims with their verified quotes, the code's
verdicts, cash facts computed from the accounts, and annual-report excerpts. Its evidence
must point back at those: claim and fact ids are checked to exist, and any annual-report
quote is looked up in the report itself. A point without evidence that checks out is
dropped.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from finn.ai.llm import LLM, Tier

# v2: v1 cited a promise as the evidence that it was on track, and wrote claim ids into
#     its prose. Code now enforces both rules as well (engine.py).
PROMPT_VERSION = "judge-v2"

SYSTEM = """You are an equity analyst holding an Indian company's management to its own words.

You get claims from its last four calls, each with an id; verdicts that code already
computed from reported numbers; facts computed from its filed accounts (ids F1, F2...);
and excerpts from its latest annual report with page numbers.

Use only what is given. Never use outside knowledge of the company, its sector, its peers
or its share price. If the material does not settle something, say so.

1. rulings: one for every claim id under "To rule on":
   verdict: met, missed, on_track, at_risk, pending (too early, no evidence either way) or
   unclear. evidence: the ids that decide it, never the promise's own id: a promise is
   not evidence that it was kept. With no other evidence, the verdict is pending or
   unclear. note: at most 20 words, the decisive fact.
   You may also add a ruling with only a note for a claim under "Graded by code", for
   example that a promise was repeated, cut, raised or moved to a later period, citing
   both ids. Never change a verdict made by code.
2. narrative: at most 45 words: where management's story and the numbers agree, and where
   they diverge. Name the specific promise and number.
3. cash_read: at most 30 words: do profits turn into cash? Use the F facts. Null if there
   are none.
4. bull and bear: up to 3 points each, at most 25 words each, the strongest first. Each
   point cites claim or fact ids in evidence, or quotes the annual report word for word in
   ar_quote (at most 30 words, copied exactly from one excerpt). For the bear case, use the
   annual report where it shows risk: an auditor's qualification or emphasis of matter,
   large contingent liabilities, material related-party dealings.
Write plain sentences: never put ids such as C3 or F1 in narrative, notes, cash_read or
points; ids go only in the evidence lists."""


class Ruling(BaseModel):
    id: str
    verdict: Literal["met", "missed", "on_track", "at_risk", "pending", "unclear"] | None = None
    note: str | None = None
    evidence: list[str] = Field(default_factory=list)


class Point(BaseModel):
    point: str
    evidence: list[str] = Field(default_factory=list)
    ar_quote: str | None = None


class JudgeOut(BaseModel):
    rulings: list[Ruling]
    narrative: str
    cash_read: str | None
    bull: list[Point]
    bear: list[Point]


def run(llm: LLM, prompt: str) -> JudgeOut:
    return llm.json(
        "judge", Tier.REASON, prompt, JudgeOut, system=SYSTEM, version=PROMPT_VERSION,
        max_output_tokens=32768,  # high thinking spends from this budget too
    )  # fmt: skip
