"""Event detection and junk-line removal, pinned to the real cases that shaped them."""

import pytest

from finn.enrich import events
from finn.textclean import clean, junk_reason

# Shaped on Nazara's board outcome of 12 October 2026: one letter, several events, filed
# under six different exchange labels.
NAZARA = """Outcome of Board Meeting
The Board of Directors at its meeting held today approved the allotment of 2,38,81,711
Equity Shares by way of Preferential Issue. The Board noted and accepted the resignation
of Mr. Rakesh Shah from the position of Chief Financial Officer and Key Managerial
Personnel. The Board approved the appointment of Mr. Arun Agrawal as Chief Financial
Officer of the Company. Mr Nitish Mittersain is not debarred under the Insolvency and
Bankruptcy Code or by any SEBI order.
For Nazara Technologies Limited
Company Secretary & Compliance Officer"""


def test_must_catch_nazara_board_outcome():
    found = events.detect(NAZARA, "Allotment of Securities", "")
    assert {"management_change", "fund_raise"} <= set(found)
    assert "litigation" not in found  # "not debarred under the Insolvency ... Code" is boilerplate


def test_signature_line_is_not_a_leadership_change():
    letter = (
        "Please take the above on record.\nFor Example Ltd\nCompany Secretary & Compliance Officer"
    )
    assert "management_change" not in events.detect(letter)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Asian Paints, 6 October: a meeting notice, not results
        ("A meeting of the Board will be held on 29th October 2026, inter alia, to consider the "
         "following: 1. Approval of audited standalone financial results for the quarter", False),
        # Eternal, 21 October: past tense is a decision
        ("The Board at its meeting held today considered and approved the unaudited financial "
         "results for the quarter ended September 30, 2026.", True),
        ("Trading window closed for declaration of unaudited financial results for the quarter", False),
    ],
)  # fmt: skip
def test_results_only_when_decided(text, expected):
    assert ("results" in events.detect(text)) is expected


def test_corporate_insolvency_still_counts():
    assert "litigation" in events.detect(
        "NCLT admitted a petition to initiate the Corporate Insolvency Resolution Process"
    )


def test_lead_event_order():
    assert events.lead_event(["dividend", "results"], "dividend") == "results"
    assert (
        events.lead_event(["fund_raise", "management_change"], "fund_raise") == "management_change"
    )
    assert events.lead_event([], "press_release") == "press_release"


def test_fingerprint_ignores_cover_page_and_spacing():
    body = " ".join(f"word{i}" for i in range(500))
    assert events.fingerprint("Cover A\n" + body) != ""
    assert events.fingerprint("  " + body.replace(" ", "\n")) == events.fingerprint(body)
    assert events.fingerprint("short letter") != events.fingerprint("another short letter")


# ---------------------------------------------------------------- junk lines


@pytest.mark.parametrize(
    "line",
    [
        "• Revenue: 803 (+53% YoY)",  # Nazara: real content that a word-shape filter dropped
        "• EBITDA: 120 (+93% YoY)",
        "Declaration of Interim Dividend of ~5/- per equity share",  # OCR turned the rupee sign into ~
        "UNLOXCYT® approved by the USFDA",  # a Sun Pharma product, not noise
        "Q2FY27 & H1FY27 Results",
    ],
)
def test_real_lines_are_kept(line):
    assert junk_reason(line) is None


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        ("माझगाव डॉक शिपशिल्डर्सशिशमटेड", "devanagari"),  # Mazagon Dock's Hindi letterhead
        ("~MAKEININDTA( ~nww~a +~~~ji~jg ~f~l9I~oss~ IiR≥.s (WW %(qi~ ~T", "ocr_noise"),
    ],
)
def test_junk_lines_are_dropped(line, reason):
    assert junk_reason(line) == reason


def test_clean_keeps_order_and_content():
    text = "माझगाव डॉक\nOutcome of Board Meeting\n~~~ji~jg ~f~l9I~\nRevenue 2,446 crore"
    assert clean(text) == "Outcome of Board Meeting\nRevenue 2,446 crore"
