"""Exchange filings: fetch, sort with rules, and read the attachment only when it matters.

Flow for each filing
1. Fetch from NSE. If NSE fails for a company, fetch the same window from BSE instead.
2. Classify with `rules.classify` on the exchange's subject line and headline.
3. Routine filings stop here: their PDFs are never downloaded.
4. Everything else gets its attachment downloaded (PDF, or PDFs inside a zip), its text
   extracted and its text quality judged. The PDF itself is kept only when the text
   layer is unusable, because the AI step will then need to look at the page images.

Runs are idempotent: a filing already processed is skipped, and a failed download is
retried on the next run.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import date, datetime, timedelta

from finn import net, rules
from finn.config import DATA_DIR, DOCS_DIR, FILINGS_LOOKBACK_DAYS, Company
from finn.pdftext import extract_any, save_text
from finn.store import now_iso, today_ist, upsert

log = logging.getLogger(__name__)

NSE_API = "https://www.nseindia.com/api/corporate-announcements"
BSE_API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
BSE_ATTACH = "https://www.bseindia.com/xml-data/corpfiling/{folder}/{name}"
MAX_ATTACHMENT_BYTES = 80 * 1024 * 1024


# ---------------------------------------------------------------- fetching


def _ist(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "+05:30"


def fetch_nse(company: Company, start: date, end: date) -> list[dict]:
    params = {
        "index": "equities",
        "symbol": company.symbol,
        "from_date": start.strftime("%d-%m-%Y"),
        "to_date": end.strftime("%d-%m-%Y"),
    }
    data = net.nse().get_json(NSE_API, params)
    if not isinstance(data, list):
        raise net.TransientHTTPError(f"unexpected NSE reply for {company.symbol}")
    out = []
    for x in data:
        try:
            filed = datetime.strptime(x["an_dt"], "%d-%b-%Y %H:%M:%S")
        except KeyError, ValueError:
            continue
        attachment = (x.get("attchmntFile") or "").strip()
        out.append(
            {
                "id": f"nse:{x.get('seq_id') or x['an_dt'] + attachment}",
                "symbol": company.symbol,
                "exchange": "NSE",
                "filed_at": _ist(filed),
                "exchange_label": (x.get("desc") or "").strip(),
                "headline": " ".join((x.get("attchmntText") or "").split()),
                "attachment_url": attachment if attachment.startswith("http") else None,
                "source_url": f"{NSE_API}?symbol={company.symbol}",
            }
        )
    return out


def fetch_bse(company: Company, bse_code: str, start: date, end: date) -> list[dict]:
    out, page = [], 1
    while page <= 20:
        params = {
            "pageno": page,
            "strCat": -1,
            "strPrevDate": start.strftime("%Y%m%d"),
            "strScrip": bse_code,
            "strSearch": "P",
            "strToDate": end.strftime("%Y%m%d"),
            "strType": "C",
            "subcategory": -1,
        }
        table = (net.bse().get_json(BSE_API, params) or {}).get("Table") or []
        if not table:
            break
        for x in table:
            try:
                filed = datetime.fromisoformat(x["NEWS_DT"].split(".")[0])
            except KeyError, ValueError:
                continue
            name = (x.get("ATTACHMENTNAME") or "").strip()
            out.append(
                {
                    "id": f"bse:{x['NEWSID']}",
                    "symbol": company.symbol,
                    "exchange": "BSE",
                    "filed_at": _ist(filed),
                    "exchange_label": " ".join((x.get("NEWSSUB") or "").split()),
                    "headline": " ".join((x.get("HEADLINE") or "").split()),
                    "attachment_url": BSE_ATTACH.format(folder="AttachLive", name=name)
                    if name
                    else None,
                    "source_url": f"{BSE_API}?strScrip={bse_code}",
                }
            )
        page += 1
    return out


def fetch_window(conn: sqlite3.Connection, company: Company, days: int) -> tuple[list[dict], str]:
    """Filings for one company, from NSE or, if NSE fails, from BSE."""
    end = today_ist()
    start = end - timedelta(days=days)
    try:
        return fetch_nse(company, start, end), "NSE"
    except (net.HTTPError, net.TransientHTTPError) as exc:
        log.warning("NSE failed for %s (%s); trying BSE", company.symbol, exc)
    code = _bse_code(conn, company.symbol)
    if not code:
        raise RuntimeError(f"no BSE code known for {company.symbol}, cannot fall back")
    return fetch_bse(company, code, start, end), "BSE"


# ---------------------------------------------------------------- processing


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def _download(url: str) -> bytes:
    try:
        return net.client_for(url).get_bytes(url)
    except net.HTTPError as exc:
        # BSE moves older attachments from AttachLive to AttachHis.
        if "/AttachLive/" in url and exc.status == 404:
            alt = url.replace("/AttachLive/", "/AttachHis/")
            return net.client_for(alt).get_bytes(alt)
        raise


def read_attachment(filing: dict) -> dict:
    """Download and extract one attachment. Returns the columns to store."""
    url = filing.get("attachment_url")
    if not url:
        return {"attachment_kind": "none", "text_quality": "no_text"}
    data = _download(url)
    if len(data) > MAX_ATTACHMENT_BYTES:
        return {"attachment_kind": "other", "text_quality": "failed"}
    if data[:4] == b"PK\x03\x04":
        kind = "zip"
    elif data[:5] == b"%PDF-":
        kind = "pdf"
    else:
        return {"attachment_kind": "other", "text_quality": "no_text"}
    extracted = extract_any(data)
    folder = DOCS_DIR / "filings" / filing["symbol"]
    stem = _safe(filing["id"])
    text_path = folder / f"{stem}.txt"
    save_text(extracted, text_path)
    cols = {
        "attachment_kind": kind,
        "text_path": text_path.relative_to(DATA_DIR).as_posix(),
        "n_pages": extracted.n_pages,
        "text_quality": extracted.quality,
        "pdf_path": None,
    }
    if extracted.quality != "ok" and kind == "pdf":
        pdf_path = folder / f"{stem}.pdf"
        pdf_path.write_bytes(data)
        cols["pdf_path"] = pdf_path.relative_to(DATA_DIR).as_posix()
    return cols


def _bse_code(conn: sqlite3.Connection, symbol: str) -> str | None:
    row = conn.execute("SELECT bse_code FROM companies WHERE symbol = ?", (symbol,)).fetchone()
    if row and row["bse_code"]:
        return row["bse_code"]
    from finn.collectors.fundamentals import company_for, resolve_bse_code

    try:
        return resolve_bse_code(conn, company_for(symbol))
    except Exception as exc:  # noqa: BLE001
        log.warning("could not resolve BSE code for %s: %s", symbol, exc)
        return None


def bse_twin(conn: sqlite3.Connection, filing: dict, window_minutes: int = 20) -> str | None:
    """The BSE copy of an NSE filing: same company, filed within a few minutes.

    Companies file the same document on both exchanges, usually within a minute or two.
    NSE's stored copy is occasionally broken (truncated on their server), and BSE's copy
    of the same filing is then the way to still read it.
    """
    code = _bse_code(conn, filing["symbol"])
    if not code:
        return None
    filed = datetime.fromisoformat(filing["filed_at"])
    day = filed.date()
    try:
        candidates = fetch_bse(company_for_symbol(filing["symbol"]), code, day, day)
    except (net.HTTPError, net.TransientHTTPError) as exc:
        log.warning("BSE lookup for %s failed: %s", filing["id"], exc)
        return None
    best, best_gap = None, timedelta(minutes=window_minutes)
    for c in candidates:
        gap = abs(datetime.fromisoformat(c["filed_at"]) - filed)
        if c["attachment_url"] and gap <= best_gap:
            best, best_gap = c["attachment_url"], gap
    return best


def company_for_symbol(symbol: str) -> Company:
    from finn.collectors.fundamentals import company_for

    return company_for(symbol)


def process(conn: sqlite3.Connection, filings: list[dict]) -> dict:
    stats = {"new": 0, "skipped_known": 0, "routine_no_download": 0, "read": 0, "failed": 0,
             "recovered_via_bse": 0}  # fmt: skip
    known = (
        {
            r["id"]: r["text_quality"]
            for r in conn.execute(
                f"SELECT id, text_quality FROM filings WHERE id IN ({','.join('?' * len(filings))})",
                [f["id"] for f in filings],
            )
        }
        if filings
        else {}
    )
    for f in filings:
        if f["id"] in known and known[f["id"]] != "failed":
            stats["skipped_known"] += 1
            continue
        verdict = rules.classify(f["exchange_label"], f["headline"])
        row = {
            **f,
            "category": verdict.category,
            "tier": verdict.tier,
            "classified_by": "rule" if verdict.category else None,
            "rule": verdict.rule,
            "needs_ai": int(verdict.needs_ai),
            "attachment_kind": None,
            "text_path": None,
            "pdf_path": None,
            "n_pages": None,
            "text_quality": "not_fetched",
            "fetched_at": now_iso(),
        }
        if verdict.needs_ai:
            try:
                row.update(read_attachment(f))
                stats["read"] += 1
            except Exception as exc:  # noqa: BLE001 - one bad PDF must not stop the run
                twin = bse_twin(conn, f) if f["exchange"] == "NSE" else None
                if twin:
                    try:
                        row.update(read_attachment({**f, "attachment_url": twin}))
                        row["attachment_url"] = twin
                        stats["read"] += 1
                        stats["recovered_via_bse"] += 1
                        log.info("recovered %s from BSE after NSE failed: %s", f["id"], exc)
                    except Exception as exc2:  # noqa: BLE001
                        exc = exc2
                        twin = None
                if not twin:
                    log.warning("attachment failed for %s: %s", f["id"], exc)
                    row["text_quality"] = "failed"
                    stats["failed"] += 1
        else:
            stats["routine_no_download"] += 1
        upsert(conn, "filings", [row], ("id",))
        stats["new"] += 1
    conn.commit()
    return stats


def run(
    conn: sqlite3.Connection, companies: list[Company], days: int = FILINGS_LOOKBACK_DAYS
) -> dict:
    total = {"companies": 0, "fetched": 0, "via_bse": [], "failed": [], "new": 0, "read": 0,
             "routine_no_download": 0, "skipped_known": 0, "attachment_failures": 0, "recovered_via_bse": 0}  # fmt: skip
    for company in companies:
        try:
            filings, source = fetch_window(conn, company, days)
        except Exception as exc:  # noqa: BLE001 - record and move on to the next company
            log.error("filings for %s failed on both exchanges: %s", company.symbol, exc)
            total["failed"].append(company.symbol)
            continue
        if source == "BSE":
            total["via_bse"].append(company.symbol)
        s = process(conn, filings)
        total["companies"] += 1
        total["fetched"] += len(filings)
        for k in ("new", "read", "routine_no_download", "skipped_known", "recovered_via_bse"):
            total[k] += s[k]
        total["attachment_failures"] += s["failed"]
        log.info(
            "%-11s %3d filings via %s, %d new, %d read",
            company.symbol,
            len(filings),
            source,
            s["new"],
            s["read"],
        )
    return total
