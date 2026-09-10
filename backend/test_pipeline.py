"""Quick end-to-end test of the pipeline against the generated sample invoices.
Run with: python3 test_pipeline.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from decision import process_invoice
from storage import load_pos, load_vendors, reset_runs, reset_pos

TEST_DIR = os.path.join(os.path.dirname(__file__), "..", "test_invoices")

CASES = [
    ("happy_path.pdf", "happy_path"),
    ("edge_missing_po.pdf", "missing_po"),
    ("edge_split_po_overage.pdf", "split_po_overage"),
    ("edge_duplicate.pdf", "duplicate_1"),
    ("edge_duplicate.pdf", "duplicate_2"),        # submitted twice on purpose
    ("edge_unapproved_vendor.pdf", "unapproved_vendor"),
    ("edge_scanned_invoice.pdf", "scanned_invoice"),
]


def main():
    reset_pos()
    reset_runs()
    vendors = load_vendors()
    runs = []

    for filename, tag in CASES:
        pos = load_pos()  # reload each time so balance updates persist across cases
        path = os.path.join(TEST_DIR, filename)
        run = process_invoice(path, filename, pos, vendors, runs, scenario_tag=tag)
        from storage import save_pos, save_run
        save_pos(pos)
        save_run(run)
        runs.append(run)

        print(f"\n{'='*70}")
        print(f"CASE: {tag}  ({filename})")
        print(f"DECISION: {run.decision}   match_confidence={run.match_confidence}  matched_po={run.matched_po}")
        for stage in run.stages:
            print(f"  [{stage.status.upper():5}] {stage.stage}: {stage.summary}")
        if run.reasons:
            print("  REASONS:")
            for r in run.reasons:
                print(f"    - {r}")

    print(f"\n{'='*70}")
    print("Final PO balances:")
    for po in load_pos():
        print(f"  {po.po_number} ({po.vendor_name}): {po.amount_invoiced_so_far:.2f} / {po.po_amount:.2f}  status={po.status}")


if __name__ == "__main__":
    main()
