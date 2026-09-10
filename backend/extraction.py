"""
Extraction: turn a raw invoice PDF into structured fields.

Two paths:
  1. LLM extraction (default) - sends the invoice text (or page image, for
     scanned invoices) to Gemini and asks for structured JSON. Handles messy,
     inconsistent vendor formats far better than regex ever could - which is
     the actual problem PS-1 describes. Uses Google's Gemini API, which has a
     genuinely free tier (no credit card) via Google AI Studio.
  2. Heuristic fallback - regex/keyword based. Used automatically if no
     GEMINI_API_KEY is configured, so the pipeline is still testable and
     demoable without a key. Add your key and the LLM path takes over.

Get a free key at https://aistudio.google.com/apikey and set GEMINI_API_KEY
in the environment (or in a .env file - see .env.example) to enable it.
"""
from __future__ import annotations
import os
import re
import io
import json
from typing import Optional
import pdfplumber
import fitz  # PyMuPDF
from PIL import Image

from models import ExtractedInvoice, LineItem

# Free-tier Gemini model. gemini-3.5-flash is Google's current stable Flash
# model as of this writing; if it's ever retired, swap in whatever Google AI
# Studio currently lists as free (e.g. gemini-3.1-flash-lite is a lighter,
# higher-rate-limit alternative on the free tier).
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
MIN_TEXT_CHARS_FOR_TEXT_MODE = 40  # below this, treat the PDF as scanned/image-based

EXTRACTION_PROMPT = """You are extracting structured data from a vendor invoice for an accounts payable system.

Return ONLY a JSON object (no markdown, no commentary) with exactly these keys:
{
  "vendor_name": string or null,
  "invoice_number": string or null,
  "invoice_date": string or null (YYYY-MM-DD if possible),
  "po_number": string or null (purchase order reference, may be labeled PO#, P.O. Number, Purchase Order, etc; null if not present anywhere on the invoice),
  "line_items": [{"description": string, "quantity": number or null, "unit_price": number or null, "amount": number or null}],
  "subtotal": number or null,
  "tax": number or null,
  "total": number or null,
  "currency": string (default "USD")
}

Rules:
- If a field is genuinely not present on the invoice, use null. Do not guess or fabricate values.
- Numbers must be plain numbers, no currency symbols or commas.
- If line items are bundled into one description, return them as a single line item.
"""


def _extract_text(pdf_path: str) -> str:
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            text_parts.append(t)
    return "\n".join(text_parts).strip()


def _page_to_image(pdf_path: str, page_num: int = 0, zoom: float = 2.0) -> Image.Image:
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")
    doc.close()
    return Image.open(io.BytesIO(img_bytes))


def _llm_available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def _get_client():
    from google import genai
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    return genai.Client(api_key=key)


def _call_llm_text(raw_text: str) -> dict:
    client = _get_client()
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=f"{EXTRACTION_PROMPT}\n\nINVOICE TEXT:\n{raw_text}",
    )
    return _parse_json_lenient(resp.text)


def _call_llm_vision(image: Image.Image) -> dict:
    client = _get_client()
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[EXTRACTION_PROMPT, image],
    )
    return _parse_json_lenient(resp.text)


def _parse_json_lenient(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# Heuristic fallback (no API key needed) - regex based, good enough to
# exercise the full pipeline end to end during development/testing.
# ---------------------------------------------------------------------------

def _heuristic_extract(raw_text: str) -> dict:
    def find(pattern, text, flags=re.IGNORECASE):
        m = re.search(pattern, text, flags)
        return m.group(1).strip() if m else None

    def find_amount(pattern, text, flags=re.IGNORECASE):
        m = re.search(pattern, text, flags)
        if not m:
            return None
        raw = m.group(1).replace(",", "").replace("$", "")
        try:
            return float(raw)
        except ValueError:
            return None

    vendor = find(r"^(.+?)\n", raw_text) or None
    # Require "Number"/"#"/"No." explicitly after "Invoice" so we don't match
    # the bare "INVOICE" heading and swallow the next word on the page.
    invoice_number = find(r"Invoice\s*(?:Number|#|No\.?)\s*:?\s*([A-Za-z0-9\-]+)", raw_text)
    invoice_date = find(r"(?:Invoice\s*Date|Date)\s*:?\s*([0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})", raw_text)
    po_number = find(r"(?:P\.?O\.?\s*(?:Number|#|No\.?)?)\s*:?\s*([A-Za-z0-9\-]+)", raw_text)
    subtotal = find_amount(r"Subtotal\s*:?\s*\$?([0-9,]+\.?[0-9]*)", raw_text)
    tax = find_amount(r"(?<!Sub)Tax\s*:?\s*\$?([0-9,]+\.?[0-9]*)", raw_text)
    # Negative lookbehind for "sub" so "Subtotal:" doesn't get matched as "Total".
    total = find_amount(r"(?<!Sub)(?<!sub)\bTotal\s*:?\s*\$?([0-9,]+\.?[0-9]*)", raw_text)

    return {
        "vendor_name": vendor,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "po_number": po_number,
        "line_items": [],
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "currency": "USD",
    }


def extract_invoice(pdf_path: str) -> ExtractedInvoice:
    notes = []
    raw_text = _extract_text(pdf_path)

    is_scanned = len(raw_text) < MIN_TEXT_CHARS_FOR_TEXT_MODE
    method = "heuristic"
    data = {}

    if is_scanned:
        notes.append("PDF had little/no extractable text; treated as a scanned image.")
        if _llm_available():
            try:
                image = _page_to_image(pdf_path)
                data = _call_llm_vision(image)
                method = "vision"
            except Exception as e:
                notes.append(f"Vision extraction failed ({e}); no data extracted.")
        else:
            notes.append("No GEMINI_API_KEY set - cannot run vision extraction on a scanned invoice. "
                          "Get a free key at https://aistudio.google.com/apikey to enable this path.")
    else:
        if _llm_available():
            try:
                data = _call_llm_text(raw_text)
                method = "text"
            except Exception as e:
                notes.append(f"LLM extraction failed ({e}); falling back to heuristic parsing.")
                data = _heuristic_extract(raw_text)
                method = "heuristic"
        else:
            data = _heuristic_extract(raw_text)
            method = "heuristic"
            notes.append("No GEMINI_API_KEY set - using heuristic regex parsing instead of the LLM extractor.")

    line_items = [LineItem(**li) for li in data.get("line_items", []) if isinstance(li, dict)]

    return ExtractedInvoice(
        vendor_name=data.get("vendor_name"),
        invoice_number=data.get("invoice_number"),
        invoice_date=data.get("invoice_date"),
        po_number=data.get("po_number"),
        line_items=line_items,
        subtotal=data.get("subtotal"),
        tax=data.get("tax"),
        total=data.get("total"),
        currency=data.get("currency", "USD"),
        extraction_method=method,
        extraction_notes=notes,
    )
