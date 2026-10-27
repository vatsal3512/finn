"""PDF text extraction with a quality verdict.

pypdfium2 (Chrome's PDF engine) was picked after a test on six real filings: it ran
5 to 60 times faster than pypdf with equal or cleaner text, and it can render pages to
images, which the AI step needs for scanned results tables.

The quality check matters more than the extractor. Some filings are scans whose embedded
OCR layer is wrong: Maruti's Q2 FY27 results read "1,005,746" as "I,005,746". Every
extractor returns the same corrupted text, so we detect it and route those pages to a
vision model instead of trusting the numbers.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

PAGE_BREAK = "\f"

# A "number-like" token: starts with a digit and contains at least two digits.
_NUMERIC = re.compile(r"(?<![A-Za-z])\d[\d,.\-]*[A-Za-z0-9]*")
# Letters that OCR typically confuses with digits, appearing inside a number.
_CONFUSED = re.compile(
    r"\d[IlOoSsEtBZ]\d"  # 5I5, 2O26
    r"|\d[,.][IlOoSsEtBZ]"  # 506.I
    r"|[IlOoSsEtBZ][,.]\d{3}"  # I,005
    r"|\d{2,}[,.]\d*[IlOoSsEtBZ]{1,2}\b"  # 36,01s
)
# Legitimate number-letter mixes in filings: FY27, Q2, 1st, 2026-27, 10th, 3x, 25cr.
_ALLOWED = re.compile(
    r"^(\d+(st|nd|rd|th|x|cr|mn|bn|lakh|k|m|b|kg|mt|mw|gw)?|\d{4}-\d{2,4}|[\d,]+(\.\d+)?)$",
    re.I,
)

GARBLED_THRESHOLD = 0.02  # share of number-like tokens that look OCR-corrupted
MIN_CHARS_PER_PAGE = 120  # below this on average, the PDF is a scan with no text layer


@dataclass(frozen=True)
class Extracted:
    pages: list[str]
    quality: str  # ok | garbled | no_text
    garble_ratio: float

    @property
    def n_pages(self) -> int:
        return len(self.pages)

    @property
    def text(self) -> str:
        return PAGE_BREAK.join(self.pages)


def assess(pages: list[str]) -> tuple[str, float]:
    chars = sum(len(p.strip()) for p in pages)
    if not pages or chars / len(pages) < MIN_CHARS_PER_PAGE:
        return "no_text", 0.0
    tokens = [t for t in _NUMERIC.findall(" ".join(pages)) if sum(ch.isdigit() for ch in t) >= 2]
    if not tokens:
        return "ok", 0.0
    suspicious = sum(1 for t in tokens if _CONFUSED.search(t) and not _ALLOWED.match(t))
    ratio = suspicious / len(tokens)
    return ("garbled" if ratio > GARBLED_THRESHOLD else "ok"), round(ratio, 4)


def extract_pdf(data: bytes) -> Extracted:
    doc = pdfium.PdfDocument(data)
    try:
        pages = []
        for i in range(len(doc)):
            page = doc[i]
            textpage = page.get_textpage()
            pages.append(textpage.get_text_range())
            textpage.close()
            page.close()
    finally:
        doc.close()
    quality, ratio = assess(pages)
    return Extracted(pages, quality, ratio)


def pdfs_in_zip(data: bytes) -> list[bytes]:
    """Some NSE filings arrive as zip files holding one or more PDFs."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = sorted(n for n in zf.namelist() if n.lower().endswith(".pdf"))
        return [zf.read(n) for n in names]


def extract_any(data: bytes) -> Extracted:
    """Extract text from a PDF or from every PDF inside a zip, as one document."""
    if data[:4] == b"PK\x03\x04":
        parts = [extract_pdf(p) for p in pdfs_in_zip(data)]
        pages = [page for part in parts for page in part.pages]
        quality, ratio = assess(pages)
        return Extracted(pages, quality, ratio)
    return extract_pdf(data)


def save_text(extracted: Extracted, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(extracted.text, encoding="utf-8")


def load_pages(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").split(PAGE_BREAK)


def render_pages(data: bytes, page_numbers: list[int], scale: float = 2.0) -> list[bytes]:
    """PNG images of the given 1-based pages, in greyscale to keep them small.

    Scale 2 is about 144 dpi: enough for a vision model to read small table digits,
    without sending megapixel images that cost more tokens.
    """
    import io as _io

    doc = pdfium.PdfDocument(data)
    images = []
    try:
        for n in page_numbers:
            if not 1 <= n <= len(doc):
                continue
            page = doc[n - 1]
            pil = page.render(scale=scale, grayscale=True).to_pil()
            buf = _io.BytesIO()
            pil.save(buf, format="PNG", optimize=True)
            images.append(buf.getvalue())
            page.close()
    finally:
        doc.close()
    return images


def find_pages(pages: list[str], pattern: str, limit: int = 12) -> list[int]:
    """1-based numbers of pages whose text matches a pattern, case-insensitively."""
    rx = re.compile(pattern, re.I)
    return [i + 1 for i, p in enumerate(pages) if rx.search(p)][:limit]
