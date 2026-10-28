"""A second reader: a model from another family checks FINN's output against its source.

FINN writes with Gemini. The checker is Groq's gpt-oss-120b, so the two do not share one
model's blind spots. It sees the full source, not just the excerpt FINN was given, so it
can also say when FINN's call was fair on what it saw but wrong on the whole filing.

A model checking a model is not proof. It is used for what code cannot see (a wrong date,
a claim the quote does not quite make, a tier that ignores the amount), and every flag it
raises is listed in the results for a person to read.
"""

from __future__ import annotations

import logging
import time
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from finn.ai.keys import keys_from_env
from finn.ai.llm import LLM, AIUnavailable, Tier
from finn.config import ROOT

log = logging.getLogger(__name__)

VERSION = "check-v1"
SOURCE_CHARS = 9000  # Groq's free tier allows about 6K prompt tokens a call
CHUNK_CHARS = 12000


def checker(conn) -> LLM:
    """Groq keys only, so every answer comes from the other model family."""
    load_dotenv(ROOT / "backend" / ".env")
    return LLM(conn, [], keys_from_env("groq", "GROQ_API_KEYS"))


def _ask(llm: LLM, task: str, prompt: str, schema, system: str):
    for attempt in range(6):  # three keys at 8K tokens a minute: wait out the minute
        try:
            return llm.json(task, Tier.LITE, prompt, schema, system=system, version=VERSION,
                            max_output_tokens=4096)  # fmt: skip
        except AIUnavailable as exc:
            log.info("checker waiting (%s): %s", attempt + 1, str(exc)[:120])
            time.sleep(65)
    return None


# ------------------------------------------------------------------ filings


class FilingCheck(BaseModel):
    unsupported: list[str] = Field(description="statements in the output the filing does not state")
    wrong: list[str] = Field(description="statements the filing contradicts")
    relevant: bool = Field(
        description="the summary says what an investor holding the stock needs to know"
    )
    why_adds: bool | None = Field(
        description="why_it_matters adds a specific fact; null when it is empty"
    )
    tier_fair: bool = Field(description="the tier fits the whole filing, amounts included")
    note: str = Field(description="one sentence: the main problem, or 'none'")


FILING_SYSTEM = """You check a summary of an Indian stock-exchange filing, written by another
model for an investor who owns the stock. Compare it with the full filing text.

- unsupported: each statement in title, summary or why_it_matters that the filing does not
  state. Fair rewording and simple comparisons with the annual revenue given are supported.
- wrong: each statement the filing contradicts (wrong number, date, person, direction).
- relevant: does the summary tell the investor what actually happened?
- why_adds: does why_it_matters add a specific fact beyond the summary? null if it is empty.
- tier_fair: tiers are must_see (could change the view on the stock), glance (worth one
  line), routine (paperwork). Judge against the whole filing, including any annexure
  amounts, and against the company's annual revenue.
Be strict and literal. Do not use outside knowledge."""


def check_filing(llm: LLM, given: str, full_text: str, output: dict) -> FilingCheck | None:
    prompt = (
        f"Facts given to the writer:\n{given.split('excerpt:')[0]}\n"
        f"Full filing text:\n{full_text[:SOURCE_CHARS]}\n\n"
        f"Output to check:\ncategory: {output['category']}\ntier: {output['tier']}\n"
        f"title: {output['title']}\nsummary: {output['summary']}\n"
        f"why_it_matters: {output['why'] or '(empty)'}"
    )
    return _ask(llm, "eval-check-filing", prompt, FilingCheck, FILING_SYSTEM)


# ------------------------------------------------------------------ quoted claims


class ItemCheck(BaseModel):
    id: str
    supported: Literal["yes", "partly", "no"]
    problem: str | None = Field(description="what the quotes do not support; null if supported")


class ItemChecks(BaseModel):
    items: list[ItemCheck]


QUOTED_SYSTEM = """You check claims written by another model about an Indian listed
company. Each claim comes with the quotes from the company's own documents that it cites,
and sometimes with figures computed by code from the filed accounts.

For each claim answer supported:
- yes: the quotes and figures state it. Fair rounding and rewording are fine.
- partly: the gist is right but a detail is not in them (a number, a period, a condition,
  a stronger word than the quote uses).
- no: they do not support it, or contradict it.
problem: name the unsupported detail. Be strict and literal. Do not use outside knowledge."""


def check_quoted(llm: LLM, items: list[dict]) -> list[ItemCheck]:
    """items: {"id", "claim", "quotes": [...], "figures": str | None}. Sent in chunks."""
    out, chunk, size = [], [], 0
    for it in items + [None]:
        text = None
        if it is not None:
            text = (
                f"[{it['id']}] claim: {it['claim']}\n"
                + "".join(f"  quote: {q}\n" for q in it["quotes"])
                + (f"  figures: {it['figures']}\n" if it.get("figures") else "")
            )
        if chunk and (it is None or size + len(text) > CHUNK_CHARS):
            res = _ask(llm, "eval-check-quoted", "Claims:\n\n" + "\n".join(chunk), ItemChecks,
                       QUOTED_SYSTEM)  # fmt: skip
            out += res.items if res else []
            chunk, size = [], 0
        if text:
            chunk.append(text)
            size += len(text)
    return out
