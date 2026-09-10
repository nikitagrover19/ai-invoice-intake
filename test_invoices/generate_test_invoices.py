"""
Generates realistic-looking invoice PDFs for testing:
  - happy_path.pdf              clean invoice, exact PO match, within tolerance
  - edge_missing_po.pdf         no PO number anywhere -> must fuzzy-match
  - edge_split_po_overage.pdf   invoice against a partially-consumed PO, overage beyond tolerance
  - edge_duplicate.pdf          submitted twice in the test harness to trigger dup detection
  - edge_unapproved_vendor.pdf  vendor exists but is not approved
  - edge_scanned_invoice.pdf    invoice rendered as an image, not machine-readable text
"""
import os
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = os.path.dirname(__file__)


def draw_invoice(c, vendor, invoice_number, invoice_date, po_number, line_items,
                  subtotal, tax, total, include_po_field=True):
    width, height = letter
    y = height - inch

    c.setFont("Helvetica-Bold", 16)
    c.drawString(inch, y, vendor)
    y -= 0.35 * inch

    c.setFont("Helvetica", 9)
    c.drawString(inch, y, "123 Commerce Way, Suite 400")
    y -= 0.18 * inch
    c.drawString(inch, y, "Springfield, IL 62704")
    y -= 0.4 * inch

    c.setFont("Helvetica-Bold", 13)
    c.drawString(inch, y, "INVOICE")
    y -= 0.3 * inch

    c.setFont("Helvetica", 10)
    c.drawString(inch, y, f"Invoice #: {invoice_number}")
    y -= 0.2 * inch
    c.drawString(inch, y, f"Invoice Date: {invoice_date}")
    y -= 0.2 * inch
    if include_po_field:
        c.drawString(inch, y, f"P.O. Number: {po_number}")
        y -= 0.2 * inch
    y -= 0.2 * inch

    # Line items table header
    c.setFont("Helvetica-Bold", 10)
    c.drawString(inch, y, "Description")
    c.drawString(4.2 * inch, y, "Qty")
    c.drawString(4.9 * inch, y, "Unit Price")
    c.drawString(6.1 * inch, y, "Amount")
    y -= 0.15 * inch
    c.line(inch, y, 7.3 * inch, y)
    y -= 0.2 * inch

    c.setFont("Helvetica", 10)
    for desc, qty, price, amt in line_items:
        c.drawString(inch, y, desc)
        c.drawString(4.2 * inch, y, str(qty))
        c.drawString(4.9 * inch, y, f"${price:,.2f}")
        c.drawString(6.1 * inch, y, f"${amt:,.2f}")
        y -= 0.22 * inch

    y -= 0.15 * inch
    c.line(4.9 * inch, y, 7.3 * inch, y)
    y -= 0.25 * inch
    c.drawString(4.9 * inch, y, "Subtotal:")
    c.drawString(6.1 * inch, y, f"${subtotal:,.2f}")
    y -= 0.22 * inch
    c.drawString(4.9 * inch, y, "Tax:")
    c.drawString(6.1 * inch, y, f"${tax:,.2f}")
    y -= 0.22 * inch
    c.setFont("Helvetica-Bold", 11)
    c.drawString(4.9 * inch, y, "Total:")
    c.drawString(6.1 * inch, y, f"${total:,.2f}")

    c.showPage()
    c.save()


def make_pdf(filename, **kwargs):
    path = os.path.join(OUT_DIR, filename)
    c = canvas.Canvas(path, pagesize=letter)
    draw_invoice(c, **kwargs)
    print(f"wrote {path}")


# 1. Happy path -------------------------------------------------------------
make_pdf(
    "happy_path.pdf",
    vendor="Northwind Office Supplies",
    invoice_number="INV-5001",
    invoice_date="2026-09-01",
    po_number="PO-1001",
    line_items=[
        ("Standing desks (adjustable)", 6, 225.00, 1350.00),
        ("Ergonomic chairs", 6, 175.00, 1050.00),
    ],
    subtotal=2400.00,
    tax=192.00,
    total=2592.00,
)

# 2. Missing PO number - must fuzzy match by vendor + amount ----------------
make_pdf(
    "edge_missing_po.pdf",
    vendor="Beacon Logistics Group",
    invoice_number="INV-7010",
    invoice_date="2026-09-02",
    po_number="",
    include_po_field=False,
    line_items=[
        ("Q3 freight consolidation services", 1, 18450.00, 18450.00),
    ],
    subtotal=18450.00,
    tax=0.00,
    total=18450.00,
)

# 3. Split PO - overage beyond tolerance but not drastic ---------------------
make_pdf(
    "edge_split_po_overage.pdf",
    vendor="Beacon Logistics Group",
    invoice_number="INV-7011",
    invoice_date="2026-09-03",
    po_number="PO-1003",
    line_items=[
        ("Warehouse handling - September", 1, 4300.00, 4300.00),
    ],
    subtotal=4300.00,
    tax=0.00,
    total=4300.00,
)
# Note: PO-1003 has po_amount=10000, amount_invoiced_so_far=6000 -> remaining=4000
# tolerance = max(4000*0.02, 50) = 80. Overage = 4300-4000 = 300 (7.5%) -> WARN/NEEDS_REVIEW

# 4. Duplicate - same file submitted twice by the test harness ---------------
make_pdf(
    "edge_duplicate.pdf",
    vendor="Northwind Office Supplies",
    invoice_number="INV-9001",
    invoice_date="2026-09-04",
    po_number="PO-1001",
    line_items=[
        ("Replacement desk parts", 4, 90.00, 360.00),
    ],
    subtotal=360.00,
    tax=28.80,
    total=388.80,
)

# 5. Unapproved vendor ---------------------------------------------------------
make_pdf(
    "edge_unapproved_vendor.pdf",
    vendor="Quickship Parcel Co",
    invoice_number="INV-3300",
    invoice_date="2026-09-05",
    po_number="PO-9999",
    line_items=[
        ("Expedited parcel delivery - August", 1, 640.00, 640.00),
    ],
    subtotal=640.00,
    tax=0.00,
    total=640.00,
)

# 6. Scanned invoice (rendered as an image, no machine-readable text) ---------
def make_scanned_invoice(filename):
    img = Image.new("RGB", (1000, 1300), "white")
    draw = ImageDraw.Draw(img)
    try:
        font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
    except Exception:
        font_big = ImageFont.load_default()
        font = ImageFont.load_default()

    y = 60
    draw.text((60, y), "Crestline Facilities Maintenance", fill="black", font=font_big); y += 60
    draw.text((60, y), "789 Industrial Pkwy, Peoria, IL 61602", fill="black", font=font); y += 60
    draw.text((60, y), "INVOICE", fill="black", font=font_big); y += 60
    draw.text((60, y), "Invoice #: INV-4420", fill="black", font=font); y += 35
    draw.text((60, y), "Date: 2026-09-05", fill="black", font=font); y += 35
    draw.text((60, y), "P.O. Number: PO-1004", fill="black", font=font); y += 60
    draw.text((60, y), "HVAC quarterly maintenance ............ $2,980.00", fill="black", font=font); y += 60
    draw.text((60, y), "Subtotal: $2,980.00", fill="black", font=font); y += 35
    draw.text((60, y), "Tax: $170.00", fill="black", font=font); y += 35
    draw.text((60, y), "Total: $3,150.00", fill="black", font=font_big)

    img_path = os.path.join(OUT_DIR, "_scanned_temp.png")
    img.save(img_path)

    pdf_path = os.path.join(OUT_DIR, filename)
    c = canvas.Canvas(pdf_path, pagesize=letter)
    width, height = letter
    c.drawImage(img_path, 0, 0, width=width, height=height)
    c.showPage()
    c.save()
    os.remove(img_path)
    print(f"wrote {pdf_path}")


make_scanned_invoice("edge_scanned_invoice.pdf")

print("\nAll test invoices generated.")
