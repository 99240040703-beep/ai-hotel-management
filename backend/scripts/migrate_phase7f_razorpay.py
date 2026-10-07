"""
Phase 7F - Razorpay additions. Additive, idempotent, non-destructive.

    python scripts/migrate_phase7f_razorpay.py            # dry run
    python scripts/migrate_phase7f_razorpay.py --apply

WHAT IT ADDS
------------
1. `payments.provider_payment_reference` - a nullable column, plus an
   index. For Razorpay the existing `provider_reference` holds the *order*
   id and this holds the *payment* id, which only exists once money moves.
   Reconciliation and support both need it.

2. `payment_webhook_events` - one new table. A provider delivers the same
   event more than once; the payment row alone cannot record that a
   particular event was already handled. `event_id` is UNIQUE, so the
   database enforces idempotency rather than trusting application code.

WHAT IT NEVER DOES
------------------
* Touch `order_headers`, `orders` or any historical row.
* Create a payment. `payments` stays at whatever it was - zero on a fresh
  database - and no bill becomes paid.
* Insert a webhook event, a placeholder or a "pending" marker.
* Backfill `provider_payment_reference` for existing rows. It is NULL for
  every development-provider payment, and inventing an id for them would
  be fabricating a provider record.

IDEMPOTENCE
-----------
Every step is guarded by an existence check. Running it twice reports no
changes.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from database import engine  # noqa: E402
from models import Base  # noqa: E402


PAYMENT_COLUMNS = [("payments", "provider_payment_reference", "VARCHAR(80)")]

# Only the two new tables/columns. Passing the full metadata would emit a
# CREATE for every table in the project.
NEW_TABLES = [Base.metadata.tables["payment_webhook_events"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    planned = []
    skipped = []

    if "payment_webhook_events" in tables:
        skipped.append("table payment_webhook_events already present")
    else:
        planned.append("CREATE TABLE payment_webhook_events")

    payment_columns = (
        {column["name"] for column in inspector.get_columns("payments")}
        if "payments" in tables
        else set()
    )

    for table, column, ddl_type in PAYMENT_COLUMNS:
        if table not in tables:
            skipped.append(f"{table} is missing")
        elif column in payment_columns:
            skipped.append(f"{table}.{column} already present")
        else:
            planned.append(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")

    for line in skipped:
        print("  " + line)

    print()
    for step in planned:
        print("  would:", step)

    if not planned:
        print("\nnothing to do - the database already has the Phase 7F shape")
        return

    if not args.apply:
        print(f"\ndry run: {len(planned)} change(s). Re-run with --apply")
        return

    with engine.begin() as connection:
        for table, column, ddl_type in PAYMENT_COLUMNS:
            if f"{table} ADD COLUMN {column}" in " ".join(planned):
                connection.execute(
                    text(f"ALTER TABLE `{table}` ADD COLUMN {column} {ddl_type}")
                )
                print(f"\n  added {table}.{column}")

                # The index is a separate statement because MySQL cannot
                # add an index and a column in one ALTER reliably across
                # versions.
                index_name = f"ix_{table}_{column}"

                connection.execute(
                    text(
                        f"CREATE INDEX {index_name} ON `{table}` ({column})"
                    )
                )
                print(f"  added index {index_name}")

        Base.metadata.create_all(bind=engine, tables=NEW_TABLES)
        print("  created table payment_webhook_events")

    print("\nverification:")

    with engine.connect() as connection:
        columns = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = DATABASE() "
                    "AND table_name = 'payments'"
                )
            )
        }

        print(
            f"  payments.provider_payment_reference: "
            f"{'present' if 'provider_payment_reference' in columns else 'MISSING'}"
        )

        events = connection.execute(
            text("SELECT COUNT(*) FROM payment_webhook_events")
        ).scalar()

        print(f"  payment_webhook_events rows: {events}")

        payments = connection.execute(
            text("SELECT COUNT(*) FROM payments")
        ).scalar()
        print(f"  payments rows: {payments} (unchanged)")

        settled = connection.execute(
            text("SELECT COUNT(*) FROM order_headers "
                 "WHERE payment_status = 'paid'")
        ).scalar()
        print(f"  orders marked paid: {settled} (must be unchanged)")

        backfilled = connection.execute(
            text("SELECT COUNT(*) FROM payments "
                 "WHERE provider_payment_reference IS NOT NULL")
        ).scalar()
        print(f"  payment references backfilled: {backfilled} (must be 0)")


if __name__ == "__main__":
    main()