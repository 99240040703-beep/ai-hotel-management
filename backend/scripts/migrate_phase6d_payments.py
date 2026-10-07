"""
Phase 6D - add the payment ledger. Safe, additive, idempotent.

    python scripts/migrate_phase6d_payments.py            # dry run
    python scripts/migrate_phase6d_payments.py --apply

WHAT IT ADDS
------------
One table, `payments`. Nothing else.

WHAT IT NEVER DOES
------------------
* Touch `order_headers`. No new column, no change to `total_amount`,
  `currency`, `payment_status` or `paid_at`. The bill stays exactly where
  Phase 2/6A left it.
* Change any historical order or its totals.
* Insert a single payment row. An empty ledger is the correct starting
  state: no money has been confirmed, so there is nothing to record.
* Mark any order paid.

IDEMPOTENCE
-----------
The table is created with `CREATE TABLE IF NOT EXISTS`, and the ORM is
asked to add only that one table. Running it twice is a no-op.

WHY A FOREIGN KEY AND NOT A PLAIN COLUMN
-----------------------------------------
Every other id in this schema is a bare Integer, because the project grew
that way. A payment is different: it is the one table whose row must not
outlive the bill it describes, because it is the only evidence that money
moved. `ON DELETE RESTRICT` makes that structural rather than a
convention - a paid bill cannot be deleted by accident.

That does mean a bill with a confirmed payment cannot be removed by any
cleanup script. That is intended: deleting a settled payment to tidy up
would erase the record of a real transaction.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from database import engine  # noqa: E402
from models import Base  # noqa: E402


PAYMENTS_TABLE = Base.metadata.tables["payments"]

# Only ever the payments table. Passing the full metadata to create_all
# would emit a CREATE for every table in the project, which on a database
# that already has them is noise at best.
TABLES = [PAYMENTS_TABLE]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    if "payments" in tables:
        print("payments                     already present")
    else:
        print("  would: CREATE TABLE payments")

    # Confirm the header columns this phase depends on are really there,
    # so a failure later cannot be mistaken for a schema problem here.
    with engine.connect() as connection:
        columns = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = DATABASE() "
                    "AND table_name = 'order_headers'"
                )
            )
        }

    print("\n  order_headers columns this phase relies on:")

    for column in ("id", "total_amount", "currency", "payment_status",
                   "paid_at", "user_id", "reference"):
        print(f"    {column:16s} "
              f"{'present' if column in columns else 'MISSING'}")

    if "payments" in tables:
        print("\nnothing to do - the payment ledger already exists")
        return

    if not args.apply:
        print("\ndry run: re-run with --apply to create the ledger")
        return

    Base.metadata.create_all(bind=engine, tables=TABLES)

    print("\nverification:")

    with engine.connect() as connection:
        rows = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = DATABASE() "
                    "AND table_name = 'payments'"
                )
            )
        }

        expected = {column.name for column in PAYMENTS_TABLE.columns}

        for column in sorted(expected):
            print(f"  payments.{column:22s} "
                  f"{'present' if column in rows else 'MISSING'}")

        if not rows:
            print("  payments table was not created")
            return

        print(f"\n  payment rows: "
              f"{connection.execute(text('SELECT COUNT(*) FROM payments')).scalar()}")

        # The decisive check: the bill side must be untouched.
        paid = connection.execute(
            text("SELECT COUNT(*) FROM order_headers "
                 "WHERE payment_status = 'paid'")
        ).scalar()

        backfilled = connection.execute(
            text("SELECT COUNT(*) FROM order_headers "
                 "WHERE paid_at IS NOT NULL")
        ).scalar()

        print(f"  orders marked paid: {paid} (must be 0)")
        print(f"  orders with paid_at: {backfilled} (must be 0)")


if __name__ == "__main__":
    main()