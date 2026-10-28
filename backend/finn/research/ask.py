""" "Ask about this": what did management say about an event, in its own words?

Every Push card has this button. For Mazagon Dock's margin collapse it answers: what did
management say about margins on its last calls, before the result came out? That turns a
pushed alert into a question about management, which is where the analysis is.

One Flash call over the two latest transcripts. The answer is shown only with at least one
quote found in those transcripts by code; otherwise FINN says the calls did not cover it.
"""

from __future__ import annotations

import sqlite3

from pydantic import BaseModel

from finn.ai.llm import LLM, Tier
from finn.contracts import AskAnswer, Evidence
from finn.research.engine import _call_label
from finn.research.extract import Call
from finn.research.gather import gather
from finn.store import now_iso

PROMPT_VERSION = "ask-v1"
CALLS = 2
MAX_QUESTION = 300
MIN_EVIDENCE_WORDS = 8  # "At this point, we can say that" is a found quote, not evidence

SYSTEM = """You answer an investor's question about an Indian listed company using only the
call transcripts given, which are its most recent.

- Use only these transcripts. Never use outside knowledge of the company or its sector.
- answer: at most 60 words of plain English, with the specific facts and numbers
  management gave and when it said them.
- quotes: up to 3 sentences that support the answer, copied word for word from the
  transcripts, each with the call label it came from.
- If the transcripts do not address the question, set addressed to false. Then say what
  management said that comes closest, or that the subject did not come up."""


class AskQuote(BaseModel):
    call: str
    quote: str


class AskOut(BaseModel):
    addressed: bool
    answer: str
    quotes: list[AskQuote]


def ask(
    conn: sqlite3.Connection, llm: LLM, symbol: str, question: str, context: str = ""
) -> AskAnswer:
    question = " ".join(question.split())[:MAX_QUESTION]
    src = gather(conn, symbol)
    docs = [d for d, _ in src.transcripts[:CALLS]]
    for d, period in src.transcripts[:CALLS]:  # "Q1 FY27 call, Aug 2026", from the filing month
        d.label = _call_label(Call(d, period, "", None, True, None))
    labels = [d.label for d in docs]
    if not docs:
        return AskAnswer(symbol=symbol, question=question, addressed=False, calls=[],
                         answer="FINN has no call transcripts for this company yet.",
                         asked_at=now_iso())  # fmt: skip
    body = "\n\n".join(f"=== {d.label} ===\n{d.text}" for d in docs)
    prompt = (f"Company: {src.name}\nQuestion: {question}\n"
              + (f"Context, from a filing: {context}\n" if context else "") + f"\n{body}")  # fmt: skip
    out = llm.json("ask", Tier.FLASH, prompt, AskOut, system=SYSTEM, version=PROMPT_VERSION)

    evidence = []
    for q in out.quotes[:3]:
        if len(q.quote.split()) < MIN_EVIDENCE_WORDS:
            continue
        doc = next((d for d in docs if d.label == q.call), None)
        for d in [doc] if doc else docs:  # a wrong call label should not lose a true quote
            m = d.find(q.quote)
            if m:
                evidence.append(Evidence(quote=m.text, source=d.label, page=m.page, url=d.url))
                break
    if not evidence:
        return AskAnswer(symbol=symbol, question=question, addressed=False, calls=labels,
                         answer="Management did not discuss this on its last two calls.",
                         model=llm.last_model, asked_at=now_iso())  # fmt: skip
    return AskAnswer(symbol=symbol, question=question, addressed=out.addressed,
                     answer=out.answer.strip(), evidence=evidence, calls=labels,
                     model=llm.last_model, asked_at=now_iso())  # fmt: skip
