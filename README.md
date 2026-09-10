# Invoice Intake — AP Processing

Takes a vendor invoice (PDF), extracts the key fields, matches it to a purchase
order, applies business rules, and produces a reasoned decision — APPROVED,
NEEDS_REVIEW, or REJECTED — with every step of the reasoning visible.

## Quick start

```bash
pip install -r requirements.txt --break-system-packages   # or use a venv
./run.sh
```

Open **http://localhost:8420**. Click any sample invoice in the left panel to
watch it run, or drag your own PDF into the dropzone. Switch to the **Ledger**
tab to see run history and live PO balances.

### Enabling real AI extraction

Without an API key, extraction falls back to heuristic regex parsing — the
whole pipeline still runs end-to-end, it's just less robust on messy/varied
invoice layouts (which is most of the point of PS-1). To use real LLM-based
extraction (handles inconsistent formats, and handles scanned/image invoices
via vision), this project uses **Google's Gemini API**, which has a genuinely
free tier — no credit card required:

```bash
cp .env.example .env
# get a free key at https://aistudio.google.com/apikey, then put it in .env:
#   GEMINI_API_KEY=AIza...
```

Restart the server after adding the key. If you hit rate limits while
rehearsing (the free tier is generous but not unlimited), switch to the
lighter `gemini-3.1-flash-lite` model by uncommenting `GEMINI_MODEL` in `.env`.

## How it works

```
PDF invoice → EXTRACT → VALIDATE → DUPLICATE CHECK → VENDOR APPROVAL
                                  → PO MATCH → AMOUNT TOLERANCE → DECISION
```

- **Extract** (`backend/extraction.py`) — pulls vendor, invoice #, date, PO #,
  line items, and totals. Uses an LLM for structured extraction when a key is
  present (text or vision, depending on whether the PDF has extractable
  text); otherwise falls back to regex heuristics.
- **Validate** — checks the fields required to make any decision at all are
  present (vendor, invoice number, total). Missing critical data routes
  straight to NEEDS_REVIEW rather than guessing.
- **Duplicate check** (`backend/rules.py`) — same vendor + invoice number
  already on file → REJECTED, with a pointer to the original run.
- **Vendor approval** — invoice from a vendor not on the approved list is
  REJECTED regardless of how well the amounts line up.
- **PO match** (`backend/matching.py`) — direct lookup by PO number; if the
  invoice doesn't reference one, falls back to matching by vendor + closest
  remaining PO balance, flagged as a lower-confidence *inferred* match.
- **Amount tolerance** — compares the invoice total against the PO's
  *remaining* balance (not the original PO amount), so partial/split
  invoices against an already-partially-consumed PO are handled correctly.
  Small overages pass, moderate overages go to review, large overages reject.
- **Decision** (`backend/decision.py`) — orchestrates the above into a final
  call with a full, visible trace. Approved invoices decrement the PO's
  remaining balance.

Data lives in plain JSON (`backend/data/`) — `po_dataset.json` (purchase
orders), `vendors.json` (approved vendor list), `runs.json` (history,
generated at runtime). No database setup needed for a demo of this size.

## The 4 edge cases

| Sample file | What it tests |
|---|---|
| `edge_missing_po.pdf` | No PO number anywhere on the invoice — must fuzzy-match by vendor + amount, flagged as lower-confidence |
| `edge_split_po_overage.pdf` | Invoice against a PO that's already partially invoiced; overage beyond tolerance but not drastic → NEEDS_REVIEW |
| `edge_duplicate.pdf` | Run it twice — second submission is auto-rejected as a duplicate |
| `edge_unapproved_vendor.pdf` | Vendor isn't on the approved list → hard reject regardless of amount match |

Bonus: `edge_scanned_invoice.pdf` is a rendered image with no machine-readable
text — without an API key it correctly explains it can't extract from a scan
rather than failing silently; with a key, it runs through the vision path.

Regenerate all sample PDFs any time with:
```bash
python3 test_invoices/generate_test_invoices.py
```

## Testing without the UI

```bash
cd backend
python3 test_pipeline.py
```
Runs every sample through the pipeline and prints the full stage-by-stage
trace for each — useful for checking logic changes quickly.

## Managing vendors and POs

You don't need to hand-edit the JSON files — the **Ledger** tab has an
"Approved vendors" panel (add a vendor, toggle approved/revoked, remove one)
and a "Purchase order balances" panel with its own "Add PO" form underneath
it. Both write straight to `backend/data/vendors.json` / `po_dataset.json`,
so anything you add there is usable immediately the next time you process an
invoice — no restart needed. Vendor-name matching is suffix-insensitive
(strips LLC/Inc/Corp/Ltd/etc. before comparing), but PO numbers still have to
match exactly.

## Resetting demo data

Click "Reset demo data" on the Ledger tab, or:
```bash
curl -X POST http://localhost:8420/api/reset
```
This clears run history and restores PO balances *and the vendor list* back
to their seed values — useful for repeating the demo cleanly before the live
interview, including undoing any vendors/POs you added while rehearsing.

## Deploying for a public link

For the case study submission you need a live, reachable URL. Fastest options
for a single FastAPI app:
- **Render** (render.com) — connect the repo, set the build command to
  `pip install -r requirements.txt` and the start command to
  `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`. Add `GEMINI_API_KEY`
  under Environment.
- **Railway** (railway.app) — same idea, auto-detects the start command from
  `run.sh` with minor tweaks, or set it explicitly as above.

Either free tier is enough for a demo of this size.

## Project layout

```
invoice-processor/
├── backend/
│   ├── main.py          FastAPI app + streaming endpoint
│   ├── models.py         Data models
│   ├── extraction.py     PDF → structured fields (LLM + heuristic fallback)
│   ├── matching.py       PO matching (exact + fuzzy)
│   ├── rules.py          Vendor approval, tolerance, duplicate checks
│   ├── decision.py       Orchestrates everything into a RunRecord
│   ├── storage.py        JSON persistence
│   ├── test_pipeline.py  CLI test harness
│   └── data/             po_dataset.json, vendors.json, runs.json
├── frontend/
│   └── index.html        Single-file UI: live run view + dashboard
├── test_invoices/
│   └── generate_test_invoices.py   generates all sample PDFs
├── requirements.txt
├── .env.example
└── run.sh
```
