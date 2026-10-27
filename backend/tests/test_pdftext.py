import io
import zipfile

from finn.pdftext import assess, extract_any, find_pages

CLEAN = (
    "Revenue from operations 533,402 524,551 423,323 1,057,959 809,253 1,832,661 "
    "Other income 4,294 18,731 9,661 Finance costs 677 635 572 FY27 Q2 1st 2026-27 "
) * 5

# Real corruption from Maruti Suzuki's Q2 FY27 results PDF, a scan with a bad OCR layer.
GARBLED = (
    "Sale ofproducts 506. I 55 499,591 I,005,746 767.564 I,743,695 Sale of sewices "
    "I 8.65 I t7,364 l 5,025 36,01s 28,584 E09.2s3 t-832-661 9.2s3 876.s80 24.s69 "
) * 5


def test_clean_numbers_pass():
    assert assess([CLEAN])[0] == "ok"


def test_ocr_corruption_is_caught():
    quality, ratio = assess([GARBLED])
    assert quality == "garbled" and ratio > 0.02


def test_scan_without_text_layer():
    assert assess(["", " ", "\n"])[0] == "no_text"


def _tiny_pdf(text: str) -> bytes:
    """A minimal one-page PDF. PDFium rebuilds the cross-reference table itself."""
    content = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    for i, body in enumerate(objs, 1):
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    return out + b"trailer << /Root 1 0 R >>\n%%EOF\n"


def test_extracts_pdf_and_pdfs_inside_zip():
    pdf = _tiny_pdf("Revenue 533402 for Q2 FY27")
    assert "Revenue 533402" in extract_any(pdf).text
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.pdf", pdf)
        zf.writestr("notes.xml", "<x/>")
        zf.writestr("b.pdf", _tiny_pdf("Second document"))
    doc = extract_any(buf.getvalue())
    assert doc.n_pages == 2 and "Second document" in doc.text


def test_find_pages_is_one_based():
    pages = [
        "cover",
        "Independent Auditor's Report on the accounts",
        "notes",
        "contingent liabilities",
    ]
    assert find_pages(pages, r"independent auditor") == [2]
    assert find_pages(pages, r"contingent liabilit") == [4]
