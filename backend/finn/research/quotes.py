"""Check that a quote the model gives is really in the document, and find its page.

The model is told to copy quotes word for word. Code then checks every one, and a claim
whose quote cannot be found is dropped, however plausible it sounds (decision D18). What
the app shows is the document's own words at the matched place, never the model's copy.

Matching ignores what PDF extraction mangles: line wraps, repeated spaces, curly quotes,
dashes and "INR946" against "INR 946". It also strips running headers, which matter in
transcripts: "Kaynes Technology India Limited August 08, 2026 Page 14 of 19" sits in the
middle of any sentence that runs over a page break.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher

_TOKEN = re.compile(r"[a-z]+|\d+")
HEADER_SHARE = 0.4  # a line on this share of pages is a running header or footer
FUZZY_MIN = 0.88  # word-sequence similarity for a quote with small slips ("you know" dropped)
MIN_QUOTE_WORDS = 4


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(_norm(text))


def _header_key(line: str) -> str:
    return re.sub(r"\d+", "#", " ".join(line.split()).lower())


def strip_running_headers(pages: list[str]) -> list[str]:
    """Drop lines that repeat on many pages once digits are ignored ("Page 3 of 19")."""
    if len(pages) < 4:
        return pages
    seen = Counter()
    for page in pages:
        seen.update({_header_key(ln) for ln in page.splitlines() if ln.strip()})
    frequent = {k for k, n in seen.items() if n >= HEADER_SHARE * len(pages)}
    return [
        "\n".join(ln for ln in page.splitlines() if _header_key(ln) not in frequent)
        for page in pages
    ]


@dataclass(frozen=True)
class Match:
    page: int  # 1-based PDF page, so a link can open the PDF at it
    text: str  # the document's own words
    exact: bool


@dataclass
class Document:
    """One source document, indexed for quote lookup."""

    label: str  # "Q1 FY27 call, 8 Aug 2026"
    url: str
    pages: list[str]
    _tokens: list[str] = field(init=False, repr=False)
    _where: list[tuple[int, int, int]] = field(init=False, repr=False)  # page, start, end
    _joined: str = field(init=False, repr=False)
    _starts: list[int] = field(init=False, repr=False)
    _grams: dict | None = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        self.pages = strip_running_headers(self.pages)
        self._tokens, self._where = [], []
        for p, page in enumerate(self.pages):
            for m in _TOKEN.finditer(_norm(page)):
                self._tokens.append(m.group())
                self._where.append((p, m.start(), m.end()))
        self._joined = " ".join(self._tokens)
        self._starts, pos = [], 0
        for t in self._tokens:
            self._starts.append(pos)
            pos += len(t) + 1

    @property
    def text(self) -> str:
        return "\n".join(self.pages)

    def _span_text(self, first: int, last: int) -> str:
        parts, current, start, prev_end = [], None, 0, 0
        for i in range(first, last + 1):
            p, s, e = self._where[i]
            if p != current:
                if current is not None:
                    parts.append(self.pages[current][start:prev_end])
                current, start = p, s
            prev_end = e
        page = self.pages[current]
        while prev_end < len(page) and page[prev_end] in "%)":  # "40%", not "40"
            prev_end += 1
        parts.append(page[start:prev_end])
        return " ".join(" ".join(part.split()) for part in parts)

    def find(self, quote: str) -> Match | None:
        q = tokens(quote)
        if len(q) < MIN_QUOTE_WORDS:
            return None
        idx = (" " + self._joined + " ").find(" " + " ".join(q) + " ")
        if idx >= 0:
            first = self._index_at(idx)
            return self._match(first, first + len(q) - 1, exact=True)
        return self._fuzzy(q)

    def _index_at(self, char_pos: int) -> int:
        lo, hi = 0, len(self._starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self._starts[mid] <= char_pos:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def _fuzzy(self, q: list[str]) -> Match | None:
        """Anchor on the quote's rarest three-word run, then compare the window around it."""
        if self._grams is None:
            self._grams = {}
            for i in range(len(self._tokens) - 2):
                self._grams.setdefault(tuple(self._tokens[i : i + 3]), []).append(i)
        grams = self._grams
        best, best_ratio = None, 0.0
        for j in range(len(q) - 2):
            for i in grams.get(tuple(q[j : j + 3]), [])[:20]:
                start = max(0, i - j - 3)
                window = self._tokens[start : start + len(q) + 6]
                sm = SequenceMatcher(None, q, window, autojunk=False)
                ratio = sm.ratio() * (len(window) + len(q)) / (2 * len(q))  # coverage of q
                if ratio > best_ratio:
                    blocks = [b for b in sm.get_matching_blocks() if b.size]
                    first = start + blocks[0].b
                    last = start + blocks[-1].b + blocks[-1].size - 1
                    best, best_ratio = (first, last), ratio
        if best and best_ratio >= FUZZY_MIN:
            return self._match(*best, exact=False)
        return None

    def _match(self, first: int, last: int, exact: bool) -> Match:
        return Match(self._where[first][0] + 1, self._span_text(first, last), exact)
