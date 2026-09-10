# Invoice Intake — AP Processing

A small AP invoice processing application.

Given a vendor invoice as a PDF, the application extracts the invoice details, finds the matching purchase order, checks the invoice against a set of business rules, and returns one of:

* `APPROVED`
* `NEEDS_REVIEW`
* `REJECTED`

The UI shows the individual checks and the reason for the final decision.

## Quick start

```bash
pip install -r requirements.txt
./run.sh
```

Open:

```text
http://localhost:8420
```

The left panel contains sample invoices. Select one to run it through the pipeline, or upload a PDF using the dropzone.

The **Ledger** tab shows previous runs, vendors, and current PO balances.

## AI extraction

The application can use Google's Gemini API for invoice extraction.

If no API key is configured, it uses the PDF text and a regex-based parser instead. This is enough to run the included examples, but it is less reliable when invoice layouts vary.

To enable Gemini:

```bash
cp .env.example .env
```

Add your key to `.env`:

```text
GEMINI_API_KEY=your_key_here
```

Restart the server after changing the environment variables.

For scanned invoices, Gemini's vision input is used when an API key is available.

## Processing flow

```text
PDF
 │
 ▼
Extract fields
 │
 ▼
Validate required fields
 │
 ├── Duplicate check
 ├── Vendor check
 ├── PO matching
 └── Amount check
 │
 ▼
Decision
```

### Extraction

`backend/extraction.py`

Extracts:

* vendor
* invoice number
* invoice date
* PO number
* line items
* invoice total

When Gemini is configured, it is used for structured extraction. PDFs with no machine-readable text can go through the vision path. Without an API key, the application falls back to local parsing.

### Validation

The application checks that the fields needed to make a decision are present.

A missing vendor, invoice number, or total results in `NEEDS_REVIEW` instead of attempting to fill in the missing value.

### Duplicate check

`backend/rules.py`

An invoice is considered a duplicate when the same vendor and invoice number already exist in the run history.

A duplicate is rejected and the previous run is included in the result.

### Vendor check

Invoices from vendors that are not on the approved vendor list are rejected.

Vendor names are normalized before comparison so common company suffixes such as `LLC`, `Inc`, `Corp`, and `Ltd` do not affect the match.

### PO matching

`backend/matching.py`

The application first looks for an exact PO number.

If the invoice does not contain a PO number, it tries to find a PO using the vendor and remaining PO balance. These matches are marked as inferred rather than exact.

### Amount check

The invoice total is compared against the **remaining** PO balance.

This matters for POs that have already been partially invoiced.

The rules are:

* within the allowed amount → continue
* small overage → continue
* moderate overage → `NEEDS_REVIEW`
* large overage → `REJECTED`

When an invoice is approved, the PO's remaining balance is updated.

### Decision

`backend/decision.py`

Coordinates the processing steps and produces a `RunRecord` containing the extracted data, checks, and final decision.

## Sample cases

The repository includes sample invoices for the main edge cases.

| File                         | Case                                                                    |
| ---------------------------- | ----------------------------------------------------------------------- |
| `edge_missing_po.pdf`        | No PO number on the invoice; the application attempts an inferred match |
| `edge_split_po_overage.pdf`  | Invoice uses a partially consumed PO and exceeds the remaining balance  |
| `edge_duplicate.pdf`         | Running the same invoice twice triggers the duplicate check             |
| `edge_unapproved_vendor.pdf` | Vendor is not on the approved vendor list                               |
| `edge_scanned_invoice.pdf`   | Scanned invoice with no machine-readable PDF text                       |
| `wildcard_novel_format.pdf`  | Invoice with a different layout from the standard samples               |

The duplicate case needs to be run twice to see the second submission rejected.

## Generating sample invoices

The sample PDFs can be regenerated with:

```bash
python3 test_invoices/generate_test_invoices.py
```

## Testing

The pipeline can also be run without the web UI:

```bash
cd backend
python3 test_pipeline.py
```

This runs the sample invoices and prints the processing steps and final decisions.

## Vendors and purchase orders

The **Ledger** tab provides controls for managing the demo data.

### Vendors

You can:

* add a vendor
* approve or revoke a vendor
* remove a vendor

Changes are written to:

```text
backend/data/vendors.json
```

### Purchase orders

You can add POs and view their remaining balances.

PO data is stored in:

```text
backend/data/po_dataset.json
```

Changes take effect on the next invoice run without restarting the server.

## Resetting the demo

The Ledger tab has a **Reset demo data** button.

The same operation can be triggered from the command line:

```bash
curl -X POST http://localhost:8420/api/reset
```

This clears the run history and restores the PO balances and vendor list from their seed files.

## Data

The application uses JSON files rather than a database:

```text
backend/data/
├── po_dataset.json
├── po_dataset.seed.json
├── vendors.json
├── vendors.seed.json
└── runs.json
```

`runs.json` contains the processing history and is updated while the application is running.

## Deployment

The application is a FastAPI service and can be deployed on platforms such as Render or Railway.

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

Set `GEMINI_API_KEY` in the platform's environment variables if Gemini extraction is required.

## Project structure

```text
ai-invoice-intake/
├── backend/
│   ├── main.py
│   ├── models.py
│   ├── extraction.py
│   ├── matching.py
│   ├── rules.py
│   ├── decision.py
│   ├── storage.py
│   ├── test_pipeline.py
│   └── data/
│       ├── po_dataset.json
│       ├── po_dataset.seed.json
│       ├── vendors.json
│       ├── vendors.seed.json
│       └── runs.json
├── frontend/
│   └── index.html
├── test_invoices/
│   ├── generate_test_invoices.py
│   └── *.pdf
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
└── run.sh
```
