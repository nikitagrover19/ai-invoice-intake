"""Match an extracted invoice to a purchase order."""
from __future__ import annotations
from typing import List, Optional, Tuple
import re
from models import ExtractedInvoice, PurchaseOrder

# Common legal-entity suffixes that show up inconsistently across a vendor's
# own invoices vs. how they're recorded in a vendor master list (e.g. an
# invoice printed as "Acme Corp, LLC" vs. a master record of just "Acme
# Corp"). Stripped only for vendor-name comparison - never for PO/invoice
# numbers, which must match exactly.
_BUSINESS_SUFFIXES = {
    "llc", "inc", "incorporated", "corp", "corporation",
    "ltd", "limited", "llp", "lp", "plc", "co", "company",
}


def _normalize(s: Optional[str]) -> str:
    """Exact-match normalization for PO numbers, invoice numbers, etc."""
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def normalize_vendor(name: Optional[str]) -> str:
    """
    Vendor-name normalization: case/punctuation-insensitive, and strips
    trailing legal-entity suffixes (LLC, Inc, Corp, Ltd, ...) so "Alderpoint
    IT Consulting" and "ALDERPOINT IT CONSULTING, LLC" are recognized as the
    same vendor. Deliberately does NOT strip generic descriptor words like
    "Group" or "Partners" since those are often part of a vendor's actual
    identity, not boilerplate.
    """
    if not name:
        return ""
    words = re.findall(r"[a-z0-9]+", name.lower())
    while words and words[-1] in _BUSINESS_SUFFIXES:
        words.pop()
    return "".join(words)


def find_match(invoice: ExtractedInvoice, pos: List[PurchaseOrder]) -> Tuple[Optional[PurchaseOrder], str]:
    """
    Returns (matched_po, confidence) where confidence is one of:
      "exact"    - matched directly on PO number
      "inferred" - PO number missing/wrong; matched by vendor + closest amount
      "none"     - no reasonable match found
    """
    # 1. Direct PO number match
    if invoice.po_number:
        target = _normalize(invoice.po_number)
        for po in pos:
            if _normalize(po.po_number) == target:
                return po, "exact"

    # 2. Fuzzy fallback: same vendor, closest remaining-balance match
    if invoice.vendor_name and invoice.total is not None:
        vendor_norm = normalize_vendor(invoice.vendor_name)
        candidates = [po for po in pos if normalize_vendor(po.vendor_name) == vendor_norm and po.status == "open"]
        if candidates:
            def distance(po: PurchaseOrder) -> float:
                remaining = po.po_amount - po.amount_invoiced_so_far
                return abs(remaining - invoice.total)
            best = min(candidates, key=distance)
            return best, "inferred"

    return None, "none"
