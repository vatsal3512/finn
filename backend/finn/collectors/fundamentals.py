"""Fundamentals for any NSE ticker: standardised tables plus the primary documents.

screener.in is used as an index, not as the source of record:
- Its financial tables give ten years of standard numbers, used for cash quality and as
  the cross-check on numbers read from results filings.
- Its document list points to the primary sources, which are downloaded from where they
  live (BSE or the company's own site): call transcripts, annual reports and results PDFs.

screener.in's terms allow personal, non-commercial use and forbid mirroring. So pages are
fetched slowly, cached locally for 12 hours, and never committed or republished.

From each annual report only three sections are located, by page number: the auditor's
report, contingent liabilities and related-party transactions (decision D6). Reading the
other few hundred pages would cost time and money for little signal.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime

from bs4 import BeautifulSoup

from finn import net
from finn.config import (
    ANNUAL_REPORTS_PER_COMPANY,
    BY_SYMBOL,
    CACHE_DIR,
    DATA_DIR,
    DOCS_DIR,
    TRANSCRIPTS_PER_COMPANY,
    Company,
)
from finn.pdftext import extract_any, find_pages, save_text
from finn.store import now_iso, upsert

log = logging.getLogger(__name__)

BASE = "https://www.screener.in/company/{symbol}/{basis}"
PAGE_CACHE_HOURS = 12
STATEMENTS = {
    "quarters": "quarters",
    "profit-loss": "profit_loss",
    "balance-sheet": "balance_sheet",
    "cash-flow": "cash_flow",
    "ratios": "ratios",
}
AR_SECTIONS = {
    "auditor_report": r"independent auditor[’'`s]* report",
    "contingent_liabilities": r"contingent liabilit",
    "related_party": r"related part(y|ies)\s+(transactions|disclosures)",
}


@dataclass
class ScreenerPage:
    symbol: str
    basis: str  # consolidated | standalone
    url: str
    soup: BeautifulSoup


# ---------------------------------------------------------------- page fetching


def _page_html(symbol: str, basis: str) -> tuple[str, str]:
    path = "consolidated/" if basis == "consolidated" else ""
    url = BASE.format(symbol=symbol, basis="").rstrip("/") + "/" + path
    cache = CACHE_DIR / "screener" / f"{symbol}-{basis}.html"
    if cache.exists() and time.time() - cache.stat().st_mtime < PAGE_CACHE_HOURS * 3600:
        return cache.read_text(encoding="utf-8"), url
    html = net.screener().get(url).text
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(html, encoding="utf-8")
    return html, url


def _has_numbers(soup: BeautifulSoup) -> bool:
    section = soup.find(id="quarters")
    table = section.find("table") if section else None
    if not table:
        return False
    cells = [td.get_text(strip=True) for td in table.select("tbody td")[1:40]]
    return sum(bool(re.search(r"\d", c)) for c in cells) >= 8


def load_page(symbol: str) -> ScreenerPage:
    """Consolidated figures when the company reports them, standalone otherwise."""
    for basis in ("consolidated", "standalone"):
        try:
            html, url = _page_html(symbol, basis)
        except net.HTTPError as exc:
            if exc.status == 404:
                continue
            raise
        soup = BeautifulSoup(html, "lxml")
        if _has_numbers(soup):
            return ScreenerPage(symbol, basis, url, soup)
    raise LookupError(f"screener.in has no financial data for {symbol}")


# ---------------------------------------------------------------- parsing


def parse_number(raw: str) -> float | None:
    s = raw.replace(",", "").replace("%", "").replace("₹", "").strip()
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_period(label: str) -> str:
    label = label.strip()
    if label.upper() == "TTM":
        return "TTM"
    try:
        return datetime.strptime(label, "%b %Y").strftime("%Y-%m")
    except ValueError:
        return label


def _clean_item(raw: str) -> str:
    return re.sub(r"\s*\+\s*$", "", " ".join(raw.replace("\xa0", " ").split()))


def parse_tables(page: ScreenerPage, fetched: str) -> list[dict]:
    rows = []
    for section_id, statement in STATEMENTS.items():
        section = page.soup.find(id=section_id)
        table = section.find("table") if section else None
        if not table or not table.find("thead"):
            continue
        periods = [
            parse_period(th.get_text(strip=True)) for th in table.find("thead").find_all("th")
        ][1:]
        for tr in table.find("tbody").find_all("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
            item = _clean_item(tds[0].get_text(" ", strip=True))
            if not item or item.lower() == "raw pdf":
                continue
            for period, td in zip(periods, tds[1:], strict=False):
                raw = td.get_text(strip=True)
                rows.append(
                    {
                        "symbol": page.symbol,
                        "basis": page.basis,
                        "statement": statement,
                        "period": period,
                        "line_item": item,
                        "value": parse_number(raw),
                        "raw": raw,
                        "source_url": page.url,
                        "fetched_at": fetched,
                    }
                )
    return rows


def parse_meta(page: ScreenerPage) -> dict:
    h1 = page.soup.find("h1")
    bse = None
    for a in page.soup.select("a[href*='bseindia.com']"):
        m = re.search(r"bseindia\.com/stock-share-price/[^/]+/[^/]+/(\d{6})", a["href"])
        if m:
            bse = m.group(1)
            break
    items = {
        _clean_item(tr.find("td").get_text(" ", strip=True))
        for tr in page.soup.select("#quarters tbody tr")
        if tr.find("td")
    }
    return {
        "name": h1.get_text(strip=True) if h1 else page.symbol,
        "bse_code": bse,
        "is_bank": int("Financing Profit" in items),
    }


def _doc_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def parse_documents(page: ScreenerPage) -> list[dict]:
    docs: list[dict] = []
    section = page.soup.find(id="documents")
    blocks = section.select(".documents") if section else []
    for block in blocks:
        heading = (block.find(["h3", "h4"]) or block).get_text(" ", strip=True).lower()
        for li in block.select("li"):
            text = " ".join(li.get_text(" ", strip=True).split())
            if heading.startswith("annual report"):
                a = li.find("a", href=True)
                year = re.search(r"(20\d\d)", text)
                if a and year:
                    docs.append(
                        _doc(
                            page,
                            "annual_report",
                            year.group(1),
                            "Annual Report " + year.group(1),
                            a["href"],
                        )
                    )
            elif heading.startswith("concall"):
                when = re.match(r"([A-Z][a-z]{2} 20\d\d)", text)
                period = parse_period(when.group(1)) if when else None
                for a in li.find_all("a", href=True):
                    label = a.get_text(strip=True).lower()
                    if label == "transcript":
                        docs.append(
                            _doc(page, "transcript", period, f"Call transcript {period}", a["href"])
                        )
                    elif label == "ppt":
                        docs.append(
                            _doc(page, "presentation", period, f"Presentation {period}", a["href"])
                        )
    # Results PDFs, one per quarter, from the "Raw PDF" row of the quarterly table.
    table = page.soup.select_one("#quarters table")
    if table and table.find("thead"):
        periods = [
            parse_period(th.get_text(strip=True)) for th in table.find("thead").find_all("th")
        ][1:]
        for tr in table.select("tbody tr"):
            first = tr.find("td")
            if first and first.get_text(strip=True).lower() == "raw pdf":
                for period, td in zip(periods, tr.find_all("td")[1:], strict=False):
                    a = td.find("a", href=True)
                    if a:
                        docs.append(_doc(page, "results", period, f"Results {period}", a["href"]))
    return docs


def _doc(page: ScreenerPage, kind: str, period: str | None, title: str, href: str) -> dict:
    url = href if href.startswith("http") else "https://www.screener.in" + href
    return {
        "id": _doc_id(url),
        "symbol": page.symbol,
        "kind": kind,
        "period": period,
        "title": title,
        "url": url,
        "source_url": page.url,
    }


# ---------------------------------------------------------------- documents


def download_document(conn: sqlite3.Connection, doc: dict) -> dict:
    """Fetch one document if we do not already have its text. Returns its stored row."""
    existing = conn.execute("SELECT * FROM documents WHERE id = ?", (doc["id"],)).fetchone()
    if existing and existing["text_path"] and (DATA_DIR / existing["text_path"]).exists():
        return dict(existing)
    data = net.client_for(doc["url"]).get_bytes(doc["url"])
    if data[:5] != b"%PDF-" and data[:4] != b"PK\x03\x04":
        raise ValueError(f"not a PDF: {doc['url']}")
    extracted = extract_any(data)
    path = DOCS_DIR / doc["kind"] / doc["symbol"] / f"{doc['period'] or 'na'}-{doc['id']}.txt"
    save_text(extracted, path)
    sections = None
    if doc["kind"] == "annual_report":
        sections = json.dumps({k: find_pages(extracted.pages, p) for k, p in AR_SECTIONS.items()})
    row = {
        **doc,
        "text_path": path.relative_to(DATA_DIR).as_posix(),
        "n_pages": extracted.n_pages,
        "text_quality": extracted.quality,
        "sections": sections,
        "fetched_at": now_iso(),
    }
    upsert(conn, "documents", [row], ("id",))
    conn.commit()
    return row


def _latest(docs: list[dict], kind: str, n: int) -> list[dict]:
    chosen = [d for d in docs if d["kind"] == kind and d["period"]]
    chosen.sort(key=lambda d: d["period"], reverse=True)
    return chosen[:n]


# ---------------------------------------------------------------- entry points


def company_for(symbol: str) -> Company:
    symbol = symbol.upper()
    return BY_SYMBOL.get(symbol) or Company(symbol, symbol, "", "", "adhoc")


def resolve_bse_code(conn: sqlite3.Connection, company: Company) -> str | None:
    page = load_page(company.symbol)
    meta = parse_meta(page)
    _save_company(conn, company, page, meta)
    return meta["bse_code"]


def _save_company(
    conn: sqlite3.Connection, company: Company, page: ScreenerPage, meta: dict
) -> None:
    upsert(
        conn,
        "companies",
        [
            {
                "symbol": company.symbol,
                "name": company.name if company.role != "adhoc" else meta["name"],
                "sector": company.sector or None,
                "size": company.size or None,
                "role": company.role,
                "bse_code": meta["bse_code"],
                "screener_url": page.url,
                "is_bank": meta["is_bank"],
                "updated_at": now_iso(),
            }
        ],
        ("symbol",),
    )


def run(
    conn: sqlite3.Connection,
    company: Company,
    transcripts: int = TRANSCRIPTS_PER_COMPANY,
    annual_reports: int = ANNUAL_REPORTS_PER_COMPANY,
) -> dict:
    page = load_page(company.symbol)
    fetched = now_iso()
    meta = parse_meta(page)
    _save_company(conn, company, page, meta)
    upsert(
        conn,
        "financials",
        parse_tables(page, fetched),
        ("symbol", "basis", "statement", "period", "line_item"),
    )
    docs = parse_documents(page)
    # Record every document we know about, so later steps can fetch more on demand.
    for d in docs:
        conn.execute(
            "INSERT OR IGNORE INTO documents (id, symbol, kind, period, title, url, source_url) "
            "VALUES (:id, :symbol, :kind, :period, :title, :url, :source_url)",
            d,
        )
    conn.commit()
    wanted = _latest(docs, "transcript", transcripts) + _latest(
        docs, "annual_report", annual_reports
    )
    stats = {"symbol": company.symbol, "basis": page.basis, "is_bank": bool(meta["is_bank"]),
             "documents_listed": len(docs), "downloaded": [], "failed": []}  # fmt: skip
    for d in wanted:
        try:
            row = download_document(conn, d)
            stats["downloaded"].append(
                f"{d['kind']} {d['period']} ({row['n_pages']} pages, {row['text_quality']})"
            )
        except Exception as exc:  # noqa: BLE001 - keep going, report at the end
            log.warning("could not fetch %s %s: %s", d["kind"], d["period"], exc)
            stats["failed"].append(f"{d['kind']} {d['period']}: {exc}")
    return stats
