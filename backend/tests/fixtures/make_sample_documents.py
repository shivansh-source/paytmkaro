"""Regenerate the synthetic sample documents in tests/fixtures/documents/.

Run from backend/:  python tests/fixtures/make_sample_documents.py

Everything is fake and stamped SAMPLE: PAN ABCDE1234F, a Verhoeff-valid but
invented Aadhaar number, "R. Kumar", "Demo Bank A". The classifier and
extractor tests reuse these files, so keep the wording document-like.
Text-layer PDFs are written by hand (no PDF writer is installed), including
a 40-bit RC4 encrypted one, the e-Aadhaar case.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import struct
import sys
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from app.documents.privacy import verhoeff_valid  # noqa: E402

OUT = Path(__file__).resolve().parent / "documents"

PAN = "ABCDE1234F"
AADHAAR = next(f"23456789012{d}" for d in "0123456789" if verhoeff_valid(f"23456789012{d}"))
# Cards print the number with wide gaps, so OCR often returns the three groups as separate boxes.
AADHAAR_GROUPED = f"{AADHAAR[:4]}   {AADHAAR[4:8]}   {AADHAAR[8:]}"
PDF_PASSWORD = "KUMA1990"  # e-Aadhaar style: first 4 letters of name + birth year


def _gstin(state: str, pan: str, entity: str = "1") -> str:
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    body = f"{state}{pan}{entity}Z"
    total = 0
    for i, ch in enumerate(body):
        product = chars.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return body + chars[(36 - total % 36) % 36]


GSTIN = _gstin("27", PAN)

# ---------- document contents (shared by every format) ----------

PAN_LINES = [
    "INCOME TAX DEPARTMENT        GOVT. OF INDIA",
    "Permanent Account Number Card",
    PAN,
    "Name",
    "R. KUMAR",
    "Father's Name",
    "S. KUMAR",
    "Date of Birth",
    "15/08/1990",
]

AADHAAR_LINES = [
    "Government of India",
    "R. Kumar",
    "DOB: 15/08/1990",
    "Male",
    AADHAAR_GROUPED,
    "Aadhaar - Mera Aadhaar, Meri Pehchan",
]

GST_LINES = [
    "Government of India",
    "Form GST REG-06",
    "[See Rule 10(1)]",
    "Registration Certificate",
    f"Registration Number: {GSTIN}",
    "1. Legal Name: R. KUMAR",
    "2. Trade Name, if any: KUMAR TRADERS",
    "3. Constitution of Business: Proprietorship",
    "4. Address of Principal Place of Business: 12, Market Road, Pune, Maharashtra, 411001",
    "5. Date of Liability: 01/04/2022",
    "6. Period of Validity: From 01/04/2022 To Not Applicable",
    "7. Type of Registration: Regular",
    "8. Particulars of Approving Authority: Goods and Services Tax Network",
    "Date of issue of Certificate: 10/04/2022",
]

STATEMENT_HEADER = ["Date", "Narration", "Chq/Ref No", "Withdrawal", "Deposit", "Balance"]


def statement_rows() -> list[list]:
    rows, balance = [], 150000.00
    entries = [
        ("UPI/412345678901/Payment from Sharma Stores", 0, 25000.00),
        ("NEFT/DEMO0002/Rent April", 18000.00, 0),
        ("UPI/412345678902/Sale proceeds", 0, 42500.50),
        ("ATM WDL/Pune Main", 5000.00, 0),
        ("IMPS/512345678903/Supplier payment", 31250.25, 0),
        ("UPI/412345678904/Payment from Mehta Traders", 0, 1500000.00),
        ("NACH/LOAN EMI/Demo NBFC B", 22500.00, 0),
    ]
    for i, (narration, debit, credit) in enumerate(entries):
        balance = round(balance - debit + credit, 2)
        rows.append([dt.date(2025, 4, 2 + i * 4), narration, f"REF{1000 + i}", debit, credit, balance])
    return rows


STATEMENT_TOP = [
    "DEMO BANK A",
    "Statement of Account",
    "Account Name: R. KUMAR (KUMAR TRADERS)",
    "Account No: XXXXXXXX4321    IFSC: DEMO0001234",
    "Period: 01-04-2025 to 30-04-2025",
    "Opening Balance: 150000.00",
]


def _money(value: float) -> str:
    return f"{value:.2f}" if value else ""


def statement_pdf_lines() -> list:
    """Same content, but table rows are cell lists so each column sits at its own x."""
    lines: list = list(STATEMENT_TOP) + [STATEMENT_HEADER]
    for d, narration, ref, debit, credit, balance in statement_rows():
        lines.append([f"{d:%d-%m-%Y}", narration, ref, _money(debit), _money(credit), f"{balance:.2f}"])
    return lines


# ---------- raster rendering ----------


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    for name in ("arialbd.ttf" if bold else "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def render_card(lines: list[str], size: tuple[int, int] = (1000, 630), font_size: int = 34) -> Image.Image:
    image = Image.new("RGB", size, (246, 242, 230))
    draw = ImageDraw.Draw(image)
    y = 30
    for i, line in enumerate(lines):
        draw.text((40, y), line, fill=(20, 20, 20), font=_font(font_size, bold=i == 0))
        y += int(font_size * 1.45)
    _stamp(image)
    return image


def render_page(lines: list[str], size: tuple[int, int] = (1240, 1754), font_size: int = 26) -> Image.Image:
    """A4 at 150 dpi, like a scanner's default."""
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    y = 90
    for line in lines:
        draw.text((80, y), line, fill="black", font=_font(font_size))
        y += int(font_size * 1.6)
    _stamp(image)
    return image


def _stamp(image: Image.Image) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(
        (image.width * 0.55, image.height * 0.75), "SAMPLE", fill=(200, 30, 30, 140), font=_font(image.width // 12, True)
    )
    image.paste(Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB"))


def jpeg_bytes(image: Image.Image, quality: int = 70) -> bytes:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=quality)
    return out.getvalue()


# ---------- minimal PDF writer (Helvetica text + optional JPEG, optional RC4-40) ----------

_PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


def _rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) % 256
        s[i], s[j] = s[j], s[i]
    out, i, j = bytearray(), 0, 0
    for byte in data:
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        out.append(byte ^ s[(s[i] + s[j]) % 256])
    return bytes(out)


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(pages: list[dict], password: str | None = None) -> bytes:
    """pages: [{"lines": [...], "image": PIL.Image | None, "stamp": bool, "size", "leading", "cols"}].
    A line is a string or, with "cols" (x positions), a list of cells. Lines become a real
    text layer; an image fills the page (a scan). Strings live only in streams, so RC4
    encryption only has to cover stream data."""
    objects: list[bytes | None] = [None, None, None]  # 1 catalog, 2 pages, 3 font
    objects[2] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    streams: dict[int, bytes] = {}
    kids = []
    for page in pages:
        resources = "/Font << /F1 3 0 R >>"
        content = []
        image = page.get("image")
        if image is not None:
            jpeg = jpeg_bytes(image, 60)
            objects.append(
                f"<< /Type /XObject /Subtype /Image /Width {image.width} /Height {image.height} "
                f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {{len}} >>".encode()
            )
            streams[len(objects)] = jpeg
            resources += f" /XObject << /Im1 {len(objects)} 0 R >>"
            content.append("q 595 0 0 842 0 0 cm /Im1 Do Q")
        y, size, leading = 800, page.get("size", 11), page.get("leading", 18)
        for line in page.get("lines", []):
            # A list is a table row: one cell per column x position in page["cols"].
            cells = [(50, line)] if isinstance(line, str) else list(zip(page["cols"], line))
            for x, text in cells:
                if text:
                    content.append(f"BT /F1 {size} Tf {x} {y} Td ({_pdf_escape(text)}) Tj ET")
            y -= leading
        if page.get("stamp", True):
            content.append("BT /F1 60 Tf 0.85 0.2 0.2 rg 330 60 Td (SAMPLE) Tj ET")
        objects.append(b"<< /Length {len} >>")
        streams[len(objects)] = "\n".join(content).encode("cp1252")
        content_ref = len(objects)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << {resources} >> "
            f"/Contents {content_ref} 0 R >>".encode()
        )
        kids.append(len(objects))
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()

    file_id = hashlib.md5(b"creditsetu-sample-" + str(len(pages)).encode()).digest()
    key = None
    if password is not None:
        permissions = -44
        padded = (password.encode() + _PAD)[:32]
        owner = _rc4(hashlib.md5(padded).digest()[:5], padded)  # owner password = user password
        key = hashlib.md5(padded + owner + struct.pack("<i", permissions) + file_id).digest()[:5]
        objects.append(
            f"<< /Filter /Standard /V 1 /R 2 /O <{owner.hex()}> /U <{_rc4(key, _PAD).hex()}> /P {permissions} >>".encode()
        )
    encrypt_ref = len(objects) if key else None

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        data = streams.get(number)
        if data is not None:
            if key:
                object_key = hashlib.md5(key + number.to_bytes(3, "little") + b"\x00\x00").digest()[:10]
                data = _rc4(object_key, data)
            body = body.replace(b"{len}", str(len(data)).encode())
            out.write(f"{number} 0 obj\n".encode() + body + b"\nstream\n" + data + b"\nendstream\nendobj\n")
        else:
            out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    trailer = f"<< /Size {len(objects) + 1} /Root 1 0 R /ID [<{file_id.hex()}> <{file_id.hex()}>]"
    if encrypt_ref:
        trailer += f" /Encrypt {encrypt_ref} 0 R"
    out.write(f"trailer\n{trailer} >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


# ---------- office files ----------


def build_docx() -> bytes:
    import docx
    from docx.shared import Inches

    document = docx.Document()
    document.add_heading("KYC documents - KUMAR TRADERS (SAMPLE)", level=1)
    document.add_paragraph("Proprietor: R. Kumar. Attached: PAN card photo and business details.")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text, table.rows[0].cells[1].text = "Field", "Value"
    for field, value in [("PAN", PAN), ("GSTIN", GSTIN), ("Constitution", "Proprietorship"), ("City", "Pune")]:
        cells = table.add_row().cells
        cells[0].text, cells[1].text = field, value
    photo = io.BytesIO(jpeg_bytes(render_card(PAN_LINES, (800, 504), 27), 60))
    document.add_picture(photo, width=Inches(4))
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def build_xlsx() -> bytes:
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Statement"
    for line in STATEMENT_TOP:
        sheet.append([line])
    sheet.append(STATEMENT_HEADER)
    for row in statement_rows():
        sheet.append(row)
    for cell in sheet["A"][len(STATEMENT_TOP) + 1 :]:
        cell.number_format = "DD-MM-YYYY"
    workbook.create_sheet("Summary").append(["Total credits", sum(r[4] for r in statement_rows())])
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def build_csv() -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(STATEMENT_HEADER)
    for d, narration, ref, debit, credit, balance in statement_rows():
        writer.writerow([f"{d:%d-%m-%Y}", narration, ref, _money(debit), _money(credit), f"{balance:.2f}"])
    return out.getvalue().encode("utf-8")


def build_ole(stream_name: str) -> bytes:
    """Not a valid compound file: just the OLE2 signature plus a directory-style UTF-16 name,
    which is all format detection looks at (legacy .doc can't be read anyway)."""
    return b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504 + stream_name.encode("utf-16-le") + b"\x00" * 512


def build_zip() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("readme.txt", "SAMPLE archive with documents inside")
    return out.getvalue()


# ---------- round 2: bureau, Udyam, financials, sanction letter, settlement ----------


def flat(line) -> str:
    return line if isinstance(line, str) else "   ".join(c for c in line if c)


def inr(value: float, decimals: int = 0) -> str:
    """Indian digit grouping: 1000000 -> 10,00,000."""
    whole, _, frac = f"{value:.{decimals}f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join([*groups, tail]) + (f".{frac}" if frac else "")


ACCOUNT_COLS = [40, 115, 185, 285, 345, 405, 465]
ENQUIRY_COLS = [40, 120, 300, 430]

CONSUMER_BUREAU = [
    "DEMO CREDIT BUREAU",
    "Consumer Credit Information Report - SAMPLE",
    "Report date: 12/06/2025",
    "Control number: DCB-2025-000417",
    "",
    "SECTION 1 - PERSONAL INFORMATION",
    "Name: R. KUMAR",
    "Date of birth: 15/08/1990",
    f"PAN: {PAN}",
    "Mobile: 9876543210",
    "Address: 12, Market Road, Pune, Maharashtra 411001",
    "",
    "SECTION 2 - CREDIT SCORE",
    "DEMO SCORE: 705",
    "Score range: 300 - 900",
    "Score date: 12/06/2025",
    "",
    "SECTION 3 - ACCOUNTS (3 accounts, 3 active)",
    ["Lender", "Type", "Account No", "Opened", "Sanctioned", "Balance", "Max DPD"],
    ["Demo Bank Z", "Term Loan", "50100234567890", "03/2023", "1,200,000", "640,500", "0"],
    ["Demo NBFC Y", "Business Loan", "LN/2023/778812", "11/2023", "500,000", "322,000", "30"],
    ["Demo Bank X", "Credit Card", "4387000012345678", "06/2022", "150,000", "45,200", "0"],
    "Overdue amount: Rs. 0",
    "Demo NBFC Y business loan was 30 days past due in January 2025 and has since been regularised.",
    "",
    "SECTION 4 - ENQUIRIES (LAST 24 MONTHS)",
    ["Date", "Member", "Purpose", "Amount"],
    ["05/05/2025", "Demo Bank A", "Business Loan", "1,000,000"],
    ["14/02/2025", "Demo NBFC B", "Business Loan", "800,000"],
    ["20/09/2024", "Demo Bank X", "Credit Card", "150,000"],
    "Enquiries in the last 12 months: 2",
    "",
    "Synthetic SAMPLE report. Not issued by any credit bureau.",
]

COMMERCIAL_BUREAU = [
    "DEMO CREDIT BUREAU",
    "Commercial Credit Report - SAMPLE",
    "Report date: 12/06/2025",
    "",
    "SECTION 1 - BORROWER",
    "Name: KUMAR TRADERS",
    "Constitution: Proprietorship",
    f"PAN: {PAN}",
    f"GSTIN: {GSTIN}",
    "Registered address: 12, Market Road, Pune, Maharashtra 411001",
    "Phone: 02025551234",
    "",
    "SECTION 2 - COMMERCIAL RANK",
    "CMR RANK: 4",
    "Rank scale: 1 (lowest risk) to 10 (highest risk)",
    "Rank date: 12/06/2025",
    "",
    "SECTION 3 - CREDIT FACILITIES",
    ["Lender", "Facility", "Account No", "Sanctioned", "Outstanding", "Max DPD", "Status"],
    ["Demo Bank Z", "Cash Credit", "30100456789012", "2,500,000", "1,980,000", "0", "Standard"],
    ["Demo NBFC Y", "Term Loan", "LN/2023/778812", "500,000", "322,000", "30", "Standard"],
    "Suit filed / wilful default: None",
    "Overdue amount: Rs. 0",
    "",
    "SECTION 4 - ENQUIRIES (LAST 24 MONTHS)",
    ["Date", "Member", "Purpose", "Amount"],
    ["05/05/2025", "Demo Bank A", "Term Loan", "1,000,000"],
    ["14/02/2025", "Demo NBFC B", "Working Capital", "800,000"],
    ["20/09/2024", "Demo Bank X", "Term Loan", "500,000"],
    "",
    "Synthetic SAMPLE report. Not issued by any credit bureau.",
]

UDYAM_LINES = [
    "UDYAM REGISTRATION CERTIFICATE - SAMPLE",
    "UDYAM REGISTRATION NUMBER: UDYAM-MH-00-1234567",
    "Name of Enterprise: KUMAR TRADERS",
    "Type of Enterprise: Small",
    "Major Activity: Trading",
    "Enterprise Owner: R. KUMAR",
    "Social Category: General",
    "Official address: 12, Market Road, Pune, Maharashtra 411001",
    "Date of Incorporation: 01/04/2022",
    "Date of Commencement of Business: 01/04/2022",
    "Date of Udyam Registration: 10/05/2022",
    "Investment in Plant and Machinery: Rs. 15,00,000",
    "Turnover: Rs. 6,12,40,000",
    ["NIC 2 digit", "NIC 4 digit", "NIC 5 digit", "Activity"],
    ["46 Wholesale trade", "4690 Non-specialised", "46900 Non-specialised", "Trading"],
    "Date of printing: 12/06/2025",
    "Synthetic SAMPLE certificate. Not issued by any government body.",
]

# (label, current, prior) in Rs. lakhs. Totals are computed so the statements always balance.
LIABILITIES = [
    ("Proprietor's capital", 120.50, 98.20),
    ("Long-term borrowings", 45.00, 52.00),
    ("Short-term borrowings", 60.00, 48.50),
    ("Trade payables", 38.75, 31.20),
    ("Other current liabilities", 12.40, 10.10),
]
ASSETS = [
    ("Fixed assets (net)", 62.30, 58.00),
    ("Non-current investments", 5.00, 5.00),
    ("Inventories", 96.40, 82.50),
    ("Trade receivables", 84.20, 70.30),
    ("Cash and bank balances", 18.75, 14.20),
    ("Other current assets", 10.00, 10.00),
]
INCOME = [("Revenue from operations", 612.40, 540.10), ("Other income", 3.60, 2.90)]
EXPENSES = [
    ("Cost of goods sold", 468.50, 415.30),
    ("Employee benefit expenses", 38.20, 34.00),
    ("Finance costs", 11.80, 12.40),
    ("Depreciation", 9.50, 8.90),
    ("Other expenses", 52.00, 47.40),
]
TAX = (9.00, 6.25)


def _total(rows, column: int) -> float:
    return round(sum(r[column] for r in rows), 2)


def _statement_rows(scale: float, fmt) -> tuple[list[list[str]], list[list[str]]]:
    """Balance sheet and P&L rows as [label, current, prior] (scaled, formatted)."""

    def row(label, cur, pri):
        return [label, fmt(cur * scale), fmt(pri * scale)]

    def total(label, rows):
        return row(label, _total(rows, 1), _total(rows, 2))

    pbt = [round(_total(INCOME, i) - _total(EXPENSES, i), 2) for i in (1, 2)]
    pat = [round(pbt[0] - TAX[0], 2), round(pbt[1] - TAX[1], 2)]
    balance_sheet = (
        [["EQUITY AND LIABILITIES", "", ""]]
        + [row(*r) for r in LIABILITIES]
        + [total("Total equity and liabilities", LIABILITIES), ["ASSETS", "", ""]]
        + [row(*r) for r in ASSETS]
        + [total("Total assets", ASSETS)]
    )
    profit_loss = (
        [row(*r) for r in INCOME]
        + [total("Total income", INCOME)]
        + [row(*r) for r in EXPENSES]
        + [total("Total expenses", EXPENSES)]
        + [row("Profit before tax", *pbt), row("Provision for tax", *TAX), row("Profit after tax", *pat)]
    )
    return balance_sheet, profit_loss


def build_financial_pdf() -> bytes:
    balance_sheet, profit_loss = _statement_rows(1, lambda v: f"{v:.2f}")
    common = {"cols": [50, 330, 420], "size": 10, "leading": 17}
    sign_off = [
        "Chartered Accountants: DEMO & ASSOCIATES (Firm Reg. No. 000000X)",
        "Audited by: CA A. Sharma, Membership No. 123456",
        "UDIN: 25123456ABCDEF1234",
        "Date: 15/09/2025 | Place: Pune",
    ]
    return build_pdf(
        [
            {
                "lines": [
                    "KUMAR TRADERS (SAMPLE)",
                    "Balance Sheet as at 31 March 2025",
                    "(Rs. in Lakhs)",
                    ["Particulars", "31-Mar-2025", "31-Mar-2024"],
                    *balance_sheet,
                    "",
                    *sign_off,
                ],
                **common,
            },
            {
                "lines": [
                    "KUMAR TRADERS (SAMPLE)",
                    "Statement of Profit and Loss for the year ended 31 March 2025",
                    "(Rs. in Lakhs)",
                    ["Particulars", "FY 2024-25", "FY 2023-24"],
                    *profit_loss,
                    "",
                    *sign_off,
                ],
                **common,
            },
        ]
    )


def build_financial_xlsx() -> bytes:
    import openpyxl

    balance_sheet, profit_loss = _statement_rows(100_000, lambda v: int(round(v)))
    workbook = openpyxl.Workbook()
    first = workbook.active
    first.title = "Balance Sheet"
    sheets = [
        (first, "Balance Sheet as at 31 March 2025", ["Particulars", "31-Mar-2025 (Provisional)", "31-Mar-2024 (Audited)"], balance_sheet),
        (workbook.create_sheet("Profit and Loss"), "Profit and Loss for FY 2024-25", ["Particulars", "FY 2024-25 (Provisional)", "FY 2023-24 (Audited)"], profit_loss),
    ]
    for sheet, title, heads, rows in sheets:
        sheet.append(["KUMAR TRADERS (SAMPLE)"])
        sheet.append([title])
        sheet.append(["(Amount in Rs.)"])
        sheet.append(heads)
        for label, current, prior in rows:
            sheet.append([label, current or None, prior or None])
        sheet.append([])
        sheet.append(["Provisional figures certified by CA A. Sharma (M. No. 123456), UDIN 25123456ABCDEF1234, 15/09/2025"])
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


# --- sanction letter ---

LOAN_AMOUNT, LOAN_RATE, LOAN_MONTHS = 1_000_000, 12.5, 36
PROCESSING_FEE = round(LOAN_AMOUNT * 0.01, 2)
FEE_GST = round(PROCESSING_FEE * 0.18, 2)


def emi_amount(principal: float = LOAN_AMOUNT, annual_pct: float = LOAN_RATE, months: int = LOAN_MONTHS) -> float:
    r = annual_pct / 1200
    return round(principal * r * (1 + r) ** months / ((1 + r) ** months - 1), 2)


def apr_percent(emi: float, net_disbursed: float, months: int) -> float:
    """Annualised IRR (monthly IRR x 12) of the cash flows the borrower actually sees."""
    low, high = 0.0, 0.1
    for _ in range(100):
        mid = (low + high) / 2
        pv = sum(emi / (1 + mid) ** k for k in range(1, months + 1))
        low, high = (mid, high) if pv > net_disbursed else (low, mid)
    return round(low * 12 * 100, 2)


def sanction_fields() -> dict[str, str]:
    emi = emi_amount()
    fees = PROCESSING_FEE + FEE_GST
    net = LOAN_AMOUNT - fees
    total_repay = round(emi * LOAN_MONTHS, 2)
    return {
        "Sanctioned loan amount": f"Rs. {inr(LOAN_AMOUNT)}",
        "Loan term": f"{LOAN_MONTHS} months",
        "Rate of interest": f"{LOAN_RATE:.2f}% per annum, fixed, reducing balance",
        "Number of instalments": str(LOAN_MONTHS),
        "EMI": f"Rs. {inr(emi, 2)}",
        "Total interest charge": f"Rs. {inr(total_repay - LOAN_AMOUNT, 2)}",
        "Processing fee": f"Rs. {inr(PROCESSING_FEE, 2)} (1.00%)",
        "GST on processing fee": f"Rs. {inr(FEE_GST, 2)} (18%)",
        "Net amount disbursed": f"Rs. {inr(net, 2)}",
        "Total amount to be paid": f"Rs. {inr(total_repay + fees, 2)}",
        "Annual Percentage Rate (APR)": f"{apr_percent(emi, net, LOAN_MONTHS):.2f}%",
        "Foreclosure charges": "2.00% of principal outstanding",
        "Penal charges on overdue": "2.00% per annum on the overdue amount",
        "Cooling-off period": "3 days from disbursal",
        "Grievance officer": "grievance@demobank-a.example",
    }


SANCTION_INTRO = [
    "DEMO BANK A",
    "SANCTION LETTER - SAMPLE",
    "Ref: DEMO/SL/2025/0042",
    "Date: 20/05/2025",
    "To: R. KUMAR, Proprietor, KUMAR TRADERS",
    "12, Market Road, Pune, Maharashtra 411001",
    "Subject: Sanction of Term Loan",
    "Dear Sir, we are pleased to sanction the following facility, subject to the terms below.",
]
SANCTION_TERMS = [
    "Facility: Term Loan",
    "Purpose: Working capital and stock purchase",
    "Security: Collateral free",
    "First EMI date: 05/07/2025, then the 5th of every month",
    "This sanction is valid for 30 days from the date of this letter.",
]


def build_sanction_pdf() -> bytes:
    lines = [*SANCTION_INTRO, "", *SANCTION_TERMS, "", "KEY FACT STATEMENT", *[[k, v] for k, v in sanction_fields().items()]]
    return build_pdf([{"lines": lines, "cols": [50, 260], "size": 10, "leading": 17}])


def build_sanction_docx() -> bytes:
    import docx

    document = docx.Document()
    document.add_heading("DEMO BANK A - SANCTION LETTER (SAMPLE)", level=1)
    for line in [*SANCTION_INTRO[2:], *SANCTION_TERMS]:
        document.add_paragraph(line)
    document.add_heading("KEY FACT STATEMENT", level=2)
    table = document.add_table(rows=0, cols=2)
    for key, value in sanction_fields().items():
        cells = table.add_row().cells
        cells[0].text, cells[1].text = key, value
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


# --- settlement report ---

SETTLEMENT_HEADER = [
    "transaction_id", "date", "payment_mode", "gross_amount", "fee", "net_amount",
    "settlement_date", "payer_upi_id", "payer_phone",
]


def settlement_rows() -> list[list]:
    """60 rows over Apr-Jun 2025. Transaction ids are 12 digits with a valid Verhoeff check
    digit, so they look exactly like an Aadhaar number: proof they are NOT masked without
    Aadhaar context. The payer columns are personal data the extractor must drop."""
    import random

    rng = random.Random(7)
    rows = []
    for i in range(60):
        day = dt.date(2025, 4, 1) + dt.timedelta(days=int(i * 89 / 59))
        mode = rng.choice(["UPI", "UPI", "UPI", "CARD", "NETBANKING", "WALLET"])
        gross = round(rng.choice([250, 499, 850, 1200, 1999, 3500, 7500, 12000]) * rng.uniform(0.9, 1.3), 2)
        fee = 0.0 if mode == "UPI" else round(gross * (0.018 if mode == "CARD" else 0.012), 2)
        base = f"4{i:010d}"
        txn = base + next(d for d in "0123456789" if verhoeff_valid(base + d))
        rows.append(
            [txn, day, mode, gross, fee, round(gross - fee, 2), day + dt.timedelta(days=1),
             f"payer{i:02d}@demoupi", f"9{rng.randrange(10**8, 10**9)}"]
        )
    return rows


def build_settlement_csv() -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(SETTLEMENT_HEADER)
    for r in settlement_rows():
        writer.writerow([r[0], f"{r[1]:%Y-%m-%d}", r[2], f"{r[3]:.2f}", f"{r[4]:.2f}", f"{r[5]:.2f}", f"{r[6]:%Y-%m-%d}", r[7], r[8]])
    return out.getvalue().encode("utf-8")


def build_settlement_xlsx() -> bytes:
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Settlements"
    sheet.append(SETTLEMENT_HEADER)
    for row in settlement_rows():
        sheet.append(row)
    for column in ("B", "G"):
        for cell in sheet[column][1:]:
            cell.number_format = "YYYY-MM-DD"
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def new_sample_files() -> dict[str, bytes]:
    def pdf(lines) -> bytes:
        # Shorter rows (the 4-cell enquiry table) simply use the first columns' x positions.
        return build_pdf([{"lines": lines, "cols": ACCOUNT_COLS, "size": 9, "leading": 16}])

    return {
        "bureau_report.pdf": pdf(CONSUMER_BUREAU),
        "bureau_report_commercial.pdf": pdf(COMMERCIAL_BUREAU),
        "bureau_report_scanned.jpg": jpeg_bytes(render_page([flat(line) for line in CONSUMER_BUREAU], font_size=24), 50),
        "udyam_certificate.pdf": build_pdf([{"lines": UDYAM_LINES, "cols": [50, 170, 290, 410], "size": 10, "leading": 20}]),
        "udyam_certificate.jpg": jpeg_bytes(render_page([flat(line) for line in UDYAM_LINES], font_size=28), 55),
        "financial_statements.pdf": build_financial_pdf(),
        "financial_statements.xlsx": build_financial_xlsx(),
        "sanction_letter.pdf": build_sanction_pdf(),
        "sanction_letter.docx": build_sanction_docx(),
        "settlement_report.csv": build_settlement_csv(),
        "settlement_report.xlsx": build_settlement_xlsx(),
    }


# ---------- write everything ----------


def main() -> None:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    OUT.mkdir(parents=True, exist_ok=True)
    pan = render_card(PAN_LINES)
    aadhaar = render_card(AADHAAR_LINES)
    files: dict[str, bytes] = {}

    def save_image(name: str, image: Image.Image, **options) -> None:
        out = io.BytesIO()
        image.save(out, **options)
        files[name] = out.getvalue()

    save_image("pan_card.jpg", pan, format="JPEG", quality=70)
    save_image("pan_card.heic", pan, format="HEIF", quality=60)
    save_image("aadhaar_front.png", aadhaar.convert("P", palette=Image.ADAPTIVE, colors=32), format="PNG")
    save_image("aadhaar_front.webp", aadhaar, format="WEBP", quality=60)
    save_image("aadhaar_front.bmp", aadhaar.resize((400, 252)).convert("L"), format="BMP")
    scans = [render_page(PAN_LINES).convert("1"), render_page(AADHAAR_LINES).convert("1")]
    out = io.BytesIO()
    scans[0].save(out, format="TIFF", compression="group4", save_all=True, append_images=scans[1:])
    files["kyc_scans_multipage.tiff"] = out.getvalue()

    files["gst_reg06.pdf"] = build_pdf([{"lines": GST_LINES}])
    files["bank_statement.pdf"] = build_pdf(
        [{"lines": statement_pdf_lines(), "cols": [40, 105, 330, 385, 445, 505], "size": 9, "leading": 16}]
    )
    files["gst_reg06_scanned.pdf"] = build_pdf([{"image": render_page(GST_LINES).resize((620, 877)), "stamp": False}])
    files["mixed_bundle.pdf"] = build_pdf(
        [
            {"lines": GST_LINES},
            {"image": render_card(PAN_LINES, (700, 441), 24), "stamp": False},
            # Scan with only a SAMPLE text-layer stamp: must still count as scanned.
            {"image": render_card(AADHAAR_LINES, (700, 441), 24), "stamp": True},
        ]
    )
    # Phone scanner app output: a full-page image plus a one-line text footer.
    files["pan_camscanner.pdf"] = build_pdf(
        [{"image": render_card(PAN_LINES, (700, 441), 24), "lines": ["Scanned with CamScanner"], "stamp": False}]
    )
    files["e_aadhaar_encrypted.pdf"] = build_pdf(
        [{"lines": ["Unique Identification Authority of India", "e-Aadhaar", *AADHAAR_LINES]}], password=PDF_PASSWORD
    )
    files["kyc_bundle.docx"] = build_docx()
    files["bank_statement.xlsx"] = build_xlsx()
    files["bank_statement.csv"] = build_csv()
    files["legacy_word.doc"] = build_ole("WordDocument")
    files["archive.zip"] = build_zip()
    files["empty.bin"] = b""
    files.update(new_sample_files())

    for name, data in files.items():
        (OUT / name).write_bytes(data)
        print(f"{name:28} {len(data) / 1024:7.1f} KB")


if __name__ == "__main__":
    main()
