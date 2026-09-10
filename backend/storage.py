"""Lightweight JSON-file persistence. Good enough for a demo; swap for a
real DB later without touching the pipeline logic.

Defaults live in backend/data/vendors.seed.json and po_dataset.seed.json -
plain, editable JSON files, not data baked into this module. The one rule
that matters: a seed file is only ever trusted after it's been parsed and
validated. Earlier versions of this file used shutil.copy(seed, live), which
happily copies an empty/corrupt seed file's emptiness straight into the live
file with no error - that's what caused the vendors.json crash. Every
function here reads and validates content before writing it anywhere.
"""
from __future__ import annotations
import json
import os
from typing import List, Optional, Type, TypeVar
from pydantic import BaseModel
from models import RunRecord, PurchaseOrder, Vendor

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PO_FILE = os.path.join(DATA_DIR, "po_dataset.json")
PO_SEED_FILE = os.path.join(DATA_DIR, "po_dataset.seed.json")
VENDOR_FILE = os.path.join(DATA_DIR, "vendors.json")
VENDOR_SEED_FILE = os.path.join(DATA_DIR, "vendors.seed.json")
RUNS_FILE = os.path.join(DATA_DIR, "runs.json")

T = TypeVar("T", bound=BaseModel)


def _read_valid(path: str, model_cls: Type[T]) -> Optional[List[T]]:
    """
    Reads and parses `path` as a JSON list of `model_cls`. Returns the parsed
    list only if the file exists, is non-empty, and is valid JSON matching
    the model. Returns None (never raises) for any other case - missing,
    empty, or corrupt - so callers can decide what to do instead of crashing.
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            raw = f.read()
        if not raw.strip():
            return None
        data = json.loads(raw)
        if not isinstance(data, list):
            return None
        return [model_cls(**d) for d in data]
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _write_list(path: str, items: List[BaseModel]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump([i.model_dump() for i in items], f, indent=2)


def _load_with_fallback(live_path: str, seed_path: str, model_cls: Type[T]) -> List[T]:
    """
    Load `live_path`. If it's missing/empty/corrupt, fall back to
    `seed_path` - but only after confirming the seed itself is valid. If
    both are broken, raises a clear, actionable error instead of a raw
    JSONDecodeError, since that's an unrecoverable setup problem the person
    running this needs to fix (restore the seed file from the project).
    """
    live = _read_valid(live_path, model_cls)
    if live is not None:
        return live

    print(f"[storage] WARNING: {live_path} is missing or unreadable; restoring from {os.path.basename(seed_path)}.")
    seed = _read_valid(seed_path, model_cls)
    if seed is None:
        raise RuntimeError(
            f"Both {os.path.basename(live_path)} and {os.path.basename(seed_path)} are missing or "
            f"corrupt - can't recover. Restore {os.path.basename(seed_path)} from the project download."
        )
    _write_list(live_path, seed)
    return seed


def load_pos() -> List[PurchaseOrder]:
    return _load_with_fallback(PO_FILE, PO_SEED_FILE, PurchaseOrder)


def save_pos(pos: List[PurchaseOrder]) -> None:
    _write_list(PO_FILE, pos)


def reset_pos() -> None:
    """Restore PO balances from po_dataset.seed.json - undoes any adds/edits/consumption."""
    seed = _read_valid(PO_SEED_FILE, PurchaseOrder)
    if seed is None:
        raise RuntimeError(f"{os.path.basename(PO_SEED_FILE)} is missing or corrupt - can't reset from it.")
    _write_list(PO_FILE, seed)


def load_vendors() -> List[Vendor]:
    return _load_with_fallback(VENDOR_FILE, VENDOR_SEED_FILE, Vendor)


def save_vendors(vendors: List[Vendor]) -> None:
    _write_list(VENDOR_FILE, vendors)


def reset_vendors() -> None:
    """Restore the vendor list from vendors.seed.json - undoes any adds/toggles/removals."""
    seed = _read_valid(VENDOR_SEED_FILE, Vendor)
    if seed is None:
        raise RuntimeError(f"{os.path.basename(VENDOR_SEED_FILE)} is missing or corrupt - can't reset from it.")
    _write_list(VENDOR_FILE, seed)


def load_runs() -> List[RunRecord]:
    runs = _read_valid(RUNS_FILE, RunRecord)
    return runs if runs is not None else []


def save_run(run: RunRecord) -> None:
    runs = load_runs()
    runs.append(run)
    _write_list(RUNS_FILE, runs)


def reset_runs() -> None:
    if os.path.exists(RUNS_FILE):
        os.remove(RUNS_FILE)
