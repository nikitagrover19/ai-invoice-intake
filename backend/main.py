import os
import re
import json
import shutil
import tempfile
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from decision import process_invoice_stream
from matching import normalize_vendor
from models import Vendor, PurchaseOrder
from storage import (load_pos, save_pos, load_vendors, save_vendors, load_runs, save_run,
                      reset_runs, reset_pos, reset_vendors)

BASE_DIR = os.path.dirname(__file__)
SAMPLES_DIR = os.path.join(BASE_DIR, "..", "test_invoices")
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")

app = FastAPI(title="Invoice Processing")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SAMPLE_FILES = {
    "happy_path.pdf": "Happy path - clean invoice, exact PO match, within tolerance",
    "edge_missing_po.pdf": "Edge case - no PO number on the invoice at all",
    "edge_split_po_overage.pdf": "Edge case - invoice pushes a partially-used PO over tolerance",
    "edge_duplicate.pdf": "Edge case - run this twice to see duplicate detection",
    "edge_unapproved_vendor.pdf": "Edge case - vendor exists but isn't approved",
    "edge_scanned_invoice.pdf": "Edge case - scanned image, no machine-readable text",
    "wildcard_novel_format.pdf": "Stress test - different vendor, totally different layout/labels",
}


class VendorCreateRequest(BaseModel):
    vendor_name: str
    approved: bool = True


class VendorUpdateRequest(BaseModel):
    approved: bool


class POCreateRequest(BaseModel):
    po_number: str
    vendor_name: str
    po_amount: float
    tolerance_pct: float = 0.02
    tolerance_min_amount: float = 25.0


def _next_vendor_id(vendors) -> str:
    nums = [int(m.group(1)) for v in vendors if (m := re.match(r"V-(\d+)", v.vendor_id))]
    return f"V-{(max(nums, default=0) + 1):02d}"


def _stream_pipeline(pdf_path: str, filename: str, scenario_tag: Optional[str] = None):
    pos = load_pos()
    vendors = load_vendors()
    existing_runs = load_runs()

    def gen():
        run = None
        for run in process_invoice_stream(pdf_path, filename, pos, vendors, existing_runs, scenario_tag):
            yield json.dumps({"type": "stage_update", "run": run.model_dump()}) + "\n"
        save_pos(pos)
        save_run(run)
        yield json.dumps({"type": "done", "run": run.model_dump()}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/invoices/upload")
async def upload_invoice(file: UploadFile = File(...)):
    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, file.filename)
    with open(tmp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    response = _stream_pipeline(tmp_path, file.filename)
    return response


@app.get("/api/samples")
def list_samples():
    return [{"filename": k, "description": v} for k, v in SAMPLE_FILES.items()]


@app.post("/api/invoices/run-sample/{filename}")
def run_sample(filename: str):
    if filename not in SAMPLE_FILES:
        return {"error": "unknown sample"}
    path = os.path.join(SAMPLES_DIR, filename)
    return _stream_pipeline(path, filename, scenario_tag=filename.replace(".pdf", ""))


@app.get("/api/runs")
def get_runs():
    runs = load_runs()
    return [r.model_dump() for r in reversed(runs)]


@app.get("/api/pos")
def get_pos():
    return [p.model_dump() for p in load_pos()]


@app.get("/api/vendors")
def get_vendors():
    return [v.model_dump() for v in load_vendors()]


@app.post("/api/vendors")
def add_vendor(body: VendorCreateRequest):
    name = body.vendor_name.strip()
    if not name:
        raise HTTPException(400, "Vendor name can't be empty.")
    vendors = load_vendors()
    norm = normalize_vendor(name)
    for v in vendors:
        if normalize_vendor(v.vendor_name) == norm:
            raise HTTPException(400, f"'{v.vendor_name}' already exists on the vendor list.")
    new_vendor = Vendor(vendor_id=_next_vendor_id(vendors), vendor_name=name, approved=body.approved)
    vendors.append(new_vendor)
    save_vendors(vendors)
    return new_vendor.model_dump()


@app.patch("/api/vendors/{vendor_id}")
def update_vendor(vendor_id: str, body: VendorUpdateRequest):
    vendors = load_vendors()
    for v in vendors:
        if v.vendor_id == vendor_id:
            v.approved = body.approved
            save_vendors(vendors)
            return v.model_dump()
    raise HTTPException(404, "Vendor not found.")


@app.delete("/api/vendors/{vendor_id}")
def delete_vendor(vendor_id: str):
    vendors = load_vendors()
    remaining = [v for v in vendors if v.vendor_id != vendor_id]
    if len(remaining) == len(vendors):
        raise HTTPException(404, "Vendor not found.")
    save_vendors(remaining)
    return {"status": "deleted"}


@app.post("/api/pos")
def add_po(body: POCreateRequest):
    po_number = body.po_number.strip()
    if not po_number:
        raise HTTPException(400, "PO number can't be empty.")
    if body.po_amount <= 0:
        raise HTTPException(400, "PO amount must be greater than zero.")
    pos = load_pos()
    for p in pos:
        if p.po_number.strip().lower() == po_number.lower():
            raise HTTPException(400, f"PO '{p.po_number}' already exists.")
    new_po = PurchaseOrder(
        po_number=po_number,
        vendor_name=body.vendor_name.strip(),
        po_amount=body.po_amount,
        amount_invoiced_so_far=0.0,
        status="open",
        tolerance_pct=body.tolerance_pct,
        tolerance_min_amount=body.tolerance_min_amount,
    )
    pos.append(new_po)
    save_pos(pos)
    return new_po.model_dump()


@app.delete("/api/pos/{po_number}")
def delete_po(po_number: str):
    pos = load_pos()
    remaining = [p for p in pos if p.po_number.strip().lower() != po_number.strip().lower()]
    if len(remaining) == len(pos):
        raise HTTPException(404, "PO not found.")
    save_pos(remaining)
    return {"status": "deleted"}


@app.post("/api/reset")
def reset():
    reset_runs()
    reset_pos()
    reset_vendors()
    return {"status": "reset"}


# Serve the frontend
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
