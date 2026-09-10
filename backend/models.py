"""Data models for the invoice processing pipeline."""
from __future__ import annotations
from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from datetime import datetime
import uuid


class LineItem(BaseModel):
    description: str
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None


class ExtractedInvoice(BaseModel):
    """What we pull out of the raw PDF. Any field can be missing."""
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    po_number: Optional[str] = None
    line_items: List[LineItem] = Field(default_factory=list)
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None
    currency: Optional[str] = "USD"
    extraction_method: Literal["text", "vision", "heuristic"] = "text"
    extraction_notes: List[str] = Field(default_factory=list)


class PurchaseOrder(BaseModel):
    po_number: str
    vendor_name: str
    po_amount: float
    amount_invoiced_so_far: float = 0.0
    status: Literal["open", "closed"] = "open"
    tolerance_pct: float = 0.02  # 2% default tolerance
    tolerance_min_amount: float = 25.0  # or $25, whichever is greater


class Vendor(BaseModel):
    vendor_name: str
    approved: bool = True
    vendor_id: str


class StageResult(BaseModel):
    """One step of the pipeline, shown in the live run view."""
    stage: str
    status: Literal["pass", "warn", "fail", "info"]
    summary: str
    details: dict = Field(default_factory=dict)


class RunRecord(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    filename: str
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    extracted: Optional[ExtractedInvoice] = None
    matched_po: Optional[str] = None
    match_confidence: Optional[Literal["exact", "inferred", "none"]] = None
    stages: List[StageResult] = Field(default_factory=list)
    decision: Literal["APPROVED", "NEEDS_REVIEW", "REJECTED", "PROCESSING"] = "PROCESSING"
    reasons: List[str] = Field(default_factory=list)
    scenario_tag: Optional[str] = None  # for demo purposes: which edge case this represents
