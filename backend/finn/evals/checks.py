"""Code checks for grounding and usefulness. No model is involved, so these give the same
answer every time and can run over every output FINN has produced.

A number counts as grounded when the source contains it, or contains a figure that rounds
to it ("40%" from "39.8%"). Years match in either form ("FY27" and "2027"), and small
numbers may be spelled out in the source ("three to four years").

A number that is a source figure times a power of ten is reported apart, as converted
(annual reports print tables in ₹ thousands, calls speak in crore and million):
"₹5,394 crore" from "INR 53.94 billion" is fair, but a slip of ten is the classic unit
error, so a person reads each one.

A name counts as grounded when each of its words appears in the source.
"""

from __future__ import annotations

import re

# Not inside another number, but glued prefixes count: "INR1,350", "Rs.594", "FY27".
_NUMBER = re.compile(r"(?<![\d,])(?<!\d\.)\d[\d,]*(?:\.\d+)?")
# Two or more capitalised words in a row: "Anup Bagchi", "Quanta Computer Inc", "ICICI Bank".
_CAP = r"(?:[A-Z][a-z]+|[A-Z]{2,})"
_NAME = re.compile(rf"\b{_CAP}(?:\s+{_CAP})+\b")
_WORD = re.compile(r"[a-z]+")
_SPELLED = {w: i for i, w in enumerate(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"])}  # fmt: skip
# Words every summary may use without the source spelling them out.
_COMMON = {
    "the", "and", "for", "with", "that", "this", "from", "its", "has", "have", "was", "are",
    "will", "into", "over", "than", "per", "cent", "company", "filing", "board", "year",
}  # fmt: skip


# Period labels are checked by code elsewhere (periods.py); their digits are not figures.
_PERIOD = re.compile(r"\b(?:Q[1-4]|H[12]|9M|FY\s?'?\d{2,4})\b")


def numbers(text: str) -> list[str]:
    return [m.group().rstrip(",") for m in _NUMBER.finditer(_PERIOD.sub(" ", text or ""))]


def _value(token: str) -> float:
    return float(token.replace(",", ""))


def _decimals(token: str) -> int:
    return len(token.split(".")[1]) if "." in token else 0


class Reference:
    """The text an output may draw on, indexed for number and word lookup."""

    def __init__(self, *texts: str):
        self.text = "\n".join(t for t in texts if t)
        self.lower = self.text.lower()
        self.words = set(_WORD.findall(self.lower))
        self.values = {_value(t) for t in numbers(self.text)}
        self.values |= {float(v) for w, v in _SPELLED.items() if w in self.words}

    def has_number(self, token: str) -> bool:
        x, d = _value(token), _decimals(token)
        if x in self.values:
            return True
        if d == 0 and 0 <= x < 100 and (2000 + x) in self.values:  # FY27 ~ 2027
            return True
        if d == 0 and 2000 <= x < 2100 and (x - 2000) in self.values:  # 2027 ~ FY27
            return True
        # Rounding is fair for figures of 10 and more; "2" from "2.4" is not a quote.
        return x >= 10 and any(round(v, d) == x for v in self.values)

    def is_converted(self, token: str) -> bool:
        x, d = _value(token), _decimals(token)
        if x < 10 or (x < 100 and d == 0):  # "40" from "4" is a coincidence, not a conversion
            return False
        return any(
            v > 0 and round(v * 10**k, d) == x for v in self.values for k in range(-12, 13) if k
        )

    def ungrounded_numbers(self, text: str) -> list[str]:
        return [t for t in numbers(text) if not self.has_number(t) and not self.is_converted(t)]

    def converted_numbers(self, text: str) -> list[str]:
        return [t for t in numbers(text) if not self.has_number(t) and self.is_converted(t)]

    def ungrounded_names(self, text: str) -> list[str]:
        """Names using a word the source never uses. A sentence's first word is skipped:
        "Replaces Sashidhar Jagdishan" capitalises a verb, not a name."""
        text, out = text or "", []
        for m in _NAME.finditer(text):
            words = _WORD.findall(m.group().lower())
            if m.start() == 0 or re.search(r"[.!?;:]\s*$", text[: m.start()]):
                words = words[1:]
            if any(w not in _COMMON and w not in self.words for w in words):
                out.append(m.group())
        return out


def content_words(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if len(w) > 3 and w not in _COMMON}


def repeats(why: str | None, summary: str | None) -> bool:
    """Most of why_it_matters is already in the summary."""
    w = content_words(why)
    return bool(w) and len(w & content_words(summary)) / len(w) >= 0.7


def specific(text: str | None) -> bool:
    """Carries a figure or a name: something true of this filing, not of all filings."""
    return bool(text) and (bool(numbers(text)) or bool(_NAME.search(text)))
