"""Orchestrates the full pipeline for one invoice and produces a RunRecord."""
from __future__ import annotations
from typing import List
from models import RunRecord, StageResult, PurchaseOrder, Vendor
from extraction import extract_invoice
from matching import find_match
from rules import check_vendor_approved, check_amount_tolerance, check_duplicate


REQUIRED_FIELDS = ["vendor_name", "invoice_number", "total"]


def process_invoice(pdf_path: str, filename: str, pos: List[PurchaseOrder],
                     vendors: List[Vendor], existing_runs: List[RunRecord],
                     scenario_tag: str = None) -> RunRecord:
    """Runs the full pipeline and returns the finished RunRecord (no streaming)."""
    run = None
    for run in process_invoice_stream(pdf_path, filename, pos, vendors, existing_runs, scenario_tag):
        pass
    return run


def process_invoice_stream(pdf_path: str, filename: str, pos: List[PurchaseOrder],
                            vendors: List[Vendor], existing_runs: List[RunRecord],
                            scenario_tag: str = None):
    """
    Generator version - yields the RunRecord after each stage is appended, so
    a caller (e.g. an API endpoint) can stream real progress to a client as
    each stage genuinely finishes, rather than faking a progress animation.
    The last yielded value is always the finished run.
    """
    run = RunRecord(filename=filename, scenario_tag=scenario_tag)

    # --- Stage 1: Extract -------------------------------------------------
    extracted = extract_invoice(pdf_path)
    run.extracted = extracted
    method_label = {"text": "text extraction", "vision": "vision (scanned page)",
                     "heuristic": "heuristic regex parsing"}[extracted.extraction_method]
    extract_summary = f"Extracted fields via {method_label}."
    if extracted.extraction_notes:
        extract_summary += " " + " ".join(extracted.extraction_notes)
    # Only flag as a warning if we actually fell back to the lower-fidelity
    # heuristic parser. A vision/text LLM read that happens to carry an
    # informational note (e.g. "this was a scanned page") is not a problem.
    extract_status = "warn" if extracted.extraction_method == "heuristic" else "info"
    run.stages.append(StageResult(
        stage="Extract",
        status=extract_status,
        summary=extract_summary,
        details={"notes": extracted.extraction_notes, "fields": extracted.model_dump()}
    ))
    yield run

    # --- Stage 2: Validate completeness ------------------------------------
    missing = [f for f in REQUIRED_FIELDS if not getattr(extracted, f)]
    if missing:
        run.stages.append(StageResult(
            stage="Validate",
            status="fail",
            summary=f"Missing required field(s): {', '.join(missing)}.",
            details={"missing_fields": missing}
        ))
        yield run
        run.decision = "NEEDS_REVIEW"
        run.reasons.append(
            f"Cannot process automatically - missing {', '.join(missing)}. "
            f"Needs a human to review the original PDF and fill these in."
        )
        yield run
        return
    else:
        run.stages.append(StageResult(
            stage="Validate",
            status="pass",
            summary="All required fields present (vendor, invoice number, total).",
        ))
        yield run

    # --- Stage 3: Duplicate check -------------------------------------------
    is_dup, dup_run_id = check_duplicate(extracted, existing_runs)
    if is_dup:
        run.stages.append(StageResult(
            stage="Duplicate check",
            status="fail",
            summary=f"Same vendor + invoice number already processed in run {dup_run_id}.",
            details={"duplicate_of_run": dup_run_id}
        ))
        yield run
        run.decision = "REJECTED"
        run.reasons.append(f"Duplicate of run {dup_run_id} - same vendor and invoice number already on file.")
        yield run
        return
    else:
        run.stages.append(StageResult(stage="Duplicate check", status="pass",
                                       summary="No matching invoice number found on file."))
        yield run

    # --- Stage 4: Vendor approval -------------------------------------------
    approved, vendor_msg = check_vendor_approved(extracted.vendor_name, vendors)
    run.stages.append(StageResult(
        stage="Vendor approval",
        status="pass" if approved else "fail",
        summary=vendor_msg,
    ))
    yield run
    if not approved:
        run.decision = "REJECTED"
        run.reasons.append(vendor_msg)
        yield run
        return

    # --- Stage 5: PO match ---------------------------------------------------
    matched_po, confidence = find_match(extracted, pos)
    run.match_confidence = confidence
    if matched_po is None:
        run.stages.append(StageResult(
            stage="PO match",
            status="fail",
            summary="No purchase order could be matched to this invoice (no PO # and no vendor/amount match).",
        ))
        yield run
        run.decision = "REJECTED"
        run.reasons.append("No matching purchase order found - cannot verify this invoice against anything on file.")
        yield run
        return

    run.matched_po = matched_po.po_number
    if confidence == "exact":
        run.stages.append(StageResult(
            stage="PO match",
            status="pass",
            summary=f"Matched directly on PO number {matched_po.po_number}.",
        ))
    else:
        run.stages.append(StageResult(
            stage="PO match",
            status="warn",
            summary=(f"Invoice did not reference a PO number. Inferred match to {matched_po.po_number} "
                     f"based on vendor name and closest remaining balance. Lower confidence - flagged for review."),
        ))
    yield run

    # --- Stage 6: Amount tolerance -------------------------------------------
    amt_status, amt_msg, overage = check_amount_tolerance(extracted.total, matched_po)
    run.stages.append(StageResult(stage="Amount check", status=amt_status, summary=amt_msg))
    yield run

    # --- Final decision --------------------------------------------------------
    if amt_status == "fail":
        run.decision = "REJECTED"
        run.reasons.append(amt_msg)
        yield run
        return

    needs_review = (confidence == "inferred") or (amt_status == "warn")
    if needs_review:
        run.decision = "NEEDS_REVIEW"
        if confidence == "inferred":
            run.reasons.append("PO match was inferred, not explicit - a human should confirm it's correct.")
        if amt_status == "warn":
            run.reasons.append(amt_msg)
        yield run
        return

    # Fully approved - update the PO's running balance (split-PO support)
    matched_po.amount_invoiced_so_far += extracted.total
    if matched_po.amount_invoiced_so_far >= matched_po.po_amount - 0.01:
        matched_po.status = "closed"
    run.decision = "APPROVED"
    run.reasons.append(
        f"Approved vendor, exact PO match, amount within tolerance. "
        f"PO {matched_po.po_number} balance updated: ${matched_po.amount_invoiced_so_far:,.2f} "
        f"of ${matched_po.po_amount:,.2f} now invoiced."
    )
    yield run
