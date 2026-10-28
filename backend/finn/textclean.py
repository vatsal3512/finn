"""Remove the two kinds of junk line that filings carry, and nothing else.

Tested on 140 real filings before adopting:
- A filter on "does this line look like words" dropped real content, such as Nazara's
  "• Revenue: 803 (+53% YoY)", and saved only 1.2% of text. Rejected.
- Cutting the first N characters loses the subject line, which often carries the key
  facts. Rejected.
- What remains is narrow: lines that are mostly Devanagari (bilingual letterheads of
  government companies, always repeated in English) and lines dense with OCR noise
  symbols such as "~MAKEININDTA( ~nww~a +~~~ji~jg". Together they are about 0.1% of the
  text, so the filter is cheap and conservative.

A line that carries a fact (a number with %, crore, lakh, or a rupee amount) is never
dropped, even when OCR turned the rupee sign into "~".
"""

from __future__ import annotations

import re
import unicodedata

# Symbols that OCR produces from scripts or stamps it cannot read. Trademark and copyright
# marks are deliberately absent: "UNLOXCYT®" is a Sun Pharma product, not noise.
NOISE = frozenset("~≥≤¢§¥°±µ¶|^`¬¦")
NOISE_SHARE = 0.08
DEVANAGARI_SHARE = 0.5
FACT = re.compile(
    r"\d[\d,.]*\s*(%|crore|cr\b|lakh|mn\b|bn\b)|₹\s*\d|~\s?\d|\b(rs\.?|inr)\s*\d", re.I
)


def junk_reason(line: str) -> str | None:
    """Why a line is junk ("devanagari" or "ocr_noise"), or None to keep it."""
    s = line.strip()
    if not s or FACT.search(s):
        return None
    letters = [ch for ch in s if ch.isalpha()]
    if letters:
        dev = sum(unicodedata.name(ch, "").startswith("DEVANAGARI") for ch in letters)
        if dev / len(letters) > DEVANAGARI_SHARE:
            return "devanagari"
    if sum(ch in NOISE for ch in s) / len(s) > NOISE_SHARE:
        return "ocr_noise"
    return None


# OCR reads the rupee sign as "~" ("interim dividend of ~5/- per share"), and a summary
# quoting that looks broken. A "~" directly before a number is a rupee sign; "~ " before
# "1,250 Crores" too. A real tilde is almost never followed by a digit in a filing.
_RUPEE = re.compile(r"~\s?(?=\d)")


def clean(text: str) -> str:
    kept = "\n".join(ln for ln in text.splitlines() if junk_reason(ln) is None)
    return _RUPEE.sub("₹", kept)
