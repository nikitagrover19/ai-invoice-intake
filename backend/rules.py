"""Business rules applied after a PO match is found (or not found)."""
from __future__ import annotations
from typing import List, Optional, Tuple
from models import ExtractedInvoice, PurchaseOrder, Vendor, RunRecord
from matching import _normalize, normalize_vendor


def check_vendor_approved(vendor_name: Optional[str], vendors: List[Vendor]) -> Tuple[bool, str]:
    if not vendor_name:
        return False, "No vendor name could be extracted from the invoice."
    norm = normalize_vendor(vendor_name)
    for v in vendors:
        if normalize_vendor(v.vendor_name) == norm:
            if v.approved:
                return True, f"'{v.vendor_name}' is an approved vendor."
            return False, f"'{v.vendor_name}' exists but is NOT on the approved vendor list."
    return False, f"'{vendor_name}' was not found in the vendor master list at all."


def check_amount_tolerance(invoice_total: Optional[float], po: PurchaseOrder) -> Tuple[str, str, float]:
    """
    Returns (status, message, overage_amount) where status is 'pass' | 'warn' | 'fail'.
    Compares invoice total against the PO's *remaining* balance, so partial
    (split) invoices against an already-partially-consumed PO are handled
    correctly.
    """
    if invoice_total is None:
        return "fail", "Invoice has no total amount to check against the PO.", 0.0

    remaining = po.po_amount - po.amount_invoiced_so_far
    tolerance = max(remaining * po.tolerance_pct, po.tolerance_min_amount)
    overage = invoice_total - remaining

    if overage <= tolerance:
        if overage > 0:
            return "pass", (f"Invoice total ${invoice_total:,.2f} exceeds remaining PO balance "
                             f"${remaining:,.2f} by ${overage:,.2f}, within tolerance of ${tolerance:,.2f}."), overage
        return "pass", (f"Invoice total ${invoice_total:,.2f} is within the remaining PO balance "
                         f"of ${remaining:,.2f}."), overage

    # overage exceeds tolerance
    overage_pct = (overage / remaining * 100) if remaining else float("inf")
    if overage_pct <= 20:
        return "warn", (f"Invoice total ${invoice_total:,.2f} exceeds remaining PO balance ${remaining:,.2f} "
                         f"by ${overage:,.2f} ({overage_pct:.1f}%), beyond the ${tolerance:,.2f} tolerance "
                         f"but not drastically."), overage
    return "fail", (f"Invoice total ${invoice_total:,.2f} exceeds remaining PO balance ${remaining:,.2f} "
                     f"by ${overage:,.2f} ({overage_pct:.1f}%) - well beyond tolerance."), overage


def check_duplicate(invoice: ExtractedInvoice, existing_runs: List[RunRecord]) -> Tuple[bool, Optional[str]]:
    """Duplicate = same vendor + same invoice number already processed (and not rejected)."""
    if not invoice.invoice_number or not invoice.vendor_name:
        return False, None
    inv_num = _normalize(invoice.invoice_number)
    vendor = normalize_vendor(invoice.vendor_name)
    for run in existing_runs:
        if run.decision == "PROCESSING":
            continue
        ext = run.extracted
        if not ext:
            continue
        if ext.invoice_number and ext.vendor_name and \
           _normalize(ext.invoice_number) == inv_num and normalize_vendor(ext.vendor_name) == vendor:
            return True, run.run_id
    return False, None
