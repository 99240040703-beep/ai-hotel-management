"""
Remove test debris left behind when a Phase 3 run was interrupted
mid-cleanup.

Deletes order headers created by the test scripts along with their
kitchen tickets and line rows. Historical seeded rows have no
order_id, so they can never be matched here.

    python scripts/cleanup_test_orders.py            # dry run
    python scripts/cleanup_test_orders.py --apply
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent),
)

from sqlalchemy import text  # noqa: E402

from database import engine  # noqa: E402


# Header ids created by the Phase 3 table tests. Anything with an
# order_id on its lines came from a checkout probe, so it is listed
# rather than pattern-matched on a date.
def run(sql, args=None):
    with engine.begin() as connection:
        result = connection.execute(text(sql), args or {})

        return result.fetchall() if result.returns_rows else result.rowcount


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")

    args = parser.parse_args()

    # Only headers that still own line rows, i.e. leftover probes.
    # A header with no lines is harmless but also reported.
    rows = run(
        "SELECT h.id, h.reference, "
        "(SELECT COUNT(*) FROM orders o WHERE o.order_id = h.id) AS line_count "
        "FROM order_headers h ORDER BY h.id"
    )

    print("order_headers currently present:")

    for header_id, reference, line_count in rows:
        print(f"  id={header_id} reference={reference} lines={line_count}")

    if not rows:
        print("\n  nothing to clean")
        return

    print(
        "\n  NOTE: this removes every order header and its lines. "
        "Historical seeded orders have no order_id and are untouched."
    )

    if not args.apply:
        print("  dry run - re-run with --apply")
        return

    header_ids = [row[0] for row in rows]
    placeholders = ",".join(str(i) for i in header_ids)

    tickets = run(
        "DELETE k FROM kitchen k JOIN orders o ON o.id = k.order_id "
        f"WHERE o.order_id IN ({placeholders})"
    )
    lines = run(f"DELETE FROM orders WHERE order_id IN ({placeholders})")
    headers = run(f"DELETE FROM order_headers WHERE id IN ({placeholders})")

    print(f"\n  deleted kitchen tickets : {tickets}")
    print(f"  deleted order lines     : {lines}")
    print(f"  deleted order headers   : {headers}")

    print("\nafter:")
    for label, sql in (
        ("orders total", "SELECT COUNT(*) FROM orders"),
        ("orders without a header", "SELECT COUNT(*) FROM orders WHERE order_id IS NULL"),
        ("orders with a header", "SELECT COUNT(*) FROM orders WHERE order_id IS NOT NULL"),
        ("order_headers", "SELECT COUNT(*) FROM order_headers"),
        ("orphan kitchen tickets",
         "SELECT COUNT(*) FROM kitchen k LEFT JOIN orders o ON o.id = k.order_id "
         "WHERE o.id IS NULL"),
    ):
        print(f"  {label:<26}: {run(sql)[0][0]}")


if __name__ == "__main__":
    main()