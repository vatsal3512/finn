"""Parser tests on a hand-written page shaped like screener.in's, so no site content is stored."""

from bs4 import BeautifulSoup

from finn.collectors.fundamentals import (
    ScreenerPage,
    parse_documents,
    parse_meta,
    parse_number,
    parse_period,
    parse_tables,
)

HTML = """
<h1>Example Industries Ltd</h1>
<a href="https://www.bseindia.com/stock-share-price/example-industries-ltd/EXMPL/500999/">BSE</a>
<section id="quarters"><table>
  <thead><tr><th></th><th>Jun 2026</th><th>Sep 2026</th></tr></thead>
  <tbody>
    <tr><td>Sales&nbsp;+</td><td>48,211</td><td>49,244</td></tr>
    <tr><td>Operating Profit</td><td>11,409</td><td>11,689</td></tr>
    <tr><td>OPM %</td><td>24%</td><td>24%</td></tr>
    <tr><td>Other Income +</td><td>984</td><td>848</td></tr>
    <tr><td>Raw PDF</td><td><a href="/company/source/quarter/1/6/2026/">pdf</a></td><td></td></tr>
  </tbody>
</table></section>
<section id="cash-flow"><table>
  <thead><tr><th></th><th>Mar 2025</th><th>Mar 2026</th></tr></thead>
  <tbody><tr><td>Cash from Operating Activity +</td><td>35,694</td><td>-</td></tr></tbody>
</table></section>
<section id="documents">
  <div class="documents annual-reports"><h3>Annual reports</h3><ul>
    <li><a href="https://www.bseindia.com/xml-data/corpfiling/AttachHis/ar2026.pdf">Annual Report 2026</a> from bse</li>
  </ul></div>
  <div class="documents concalls"><h3>Concalls</h3><ul>
    <li>Oct 2026 <span>Transcript</span> <a href="https://example.com/q2.pptx">PPT</a></li>
    <li>Jul 2026 <a href="https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname=q1.pdf">Transcript</a></li>
  </ul></div>
</section>
"""


def _page():
    return ScreenerPage(
        "EXMPL",
        "consolidated",
        "https://www.screener.in/company/EXMPL/consolidated/",
        BeautifulSoup(HTML, "lxml"),
    )


def test_numbers_and_periods():
    assert parse_number("1,05,746") == 105746.0
    assert parse_number("24%") == 24.0
    assert parse_number("-") is None and parse_number("") is None
    assert parse_period("Sep 2026") == "2026-09" and parse_period("TTM") == "TTM"


def test_tables_are_long_form_with_provenance():
    rows = parse_tables(_page(), "2026-10-27T00:00:00+00:00")
    sales = {r["period"]: r["value"] for r in rows if r["line_item"] == "Sales"}
    assert sales == {"2026-06": 48211.0, "2026-09": 49244.0}
    assert all(r["source_url"].startswith("https://www.screener.in/") for r in rows)
    assert not any(r["line_item"] == "Raw PDF" for r in rows)
    cfo = [r for r in rows if r["statement"] == "cash_flow"]
    assert cfo[0]["line_item"] == "Cash from Operating Activity" and cfo[1]["value"] is None


def test_meta():
    meta = parse_meta(_page())
    assert meta == {"name": "Example Industries Ltd", "bse_code": "500999", "is_bank": 0}


def test_documents_skip_unlinked_transcripts():
    docs = parse_documents(_page())
    kinds = {(d["kind"], d["period"]) for d in docs}
    assert ("transcript", "2026-07") in kinds
    assert ("transcript", "2026-10") not in kinds  # listed but not yet linked
    assert ("presentation", "2026-10") in kinds
    assert ("annual_report", "2026") in kinds
    assert ("results", "2026-06") in kinds
    assert all(d["url"].startswith("https://") for d in docs)
