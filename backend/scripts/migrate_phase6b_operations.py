"""
Phase 6C - add operational history. Safe, additive, idempotent.

    python scripts/migrate_phase6b_operations.py            # dry run
    python scripts/migrate_phase6b_operations.py --apply

WHAT IT ADDS
------------
1. Table `restaurant_events` - the operational event log.
2. `order_headers.status_changed_at` - when the current status was entered.
3. `order_headers.completed_at`     - when the food reached the guest.
4. `order_headers.paid_at`          - when a provider confirmed payment.
5. `reservations.updated_at`        - when a booking last changed.

WHAT IT NEVER DOES
------------------
* DROP, TRUNCATE or UPDATE any historical row.
* Backfill a timestamp. The three new order_headers columns stay NULL on
  every existing row, because the moment those transitions happened was
  never recorded and inventing it would be worse than admitting the gap.
* Change any column type, name or index that already exists.

IDEMPOTENCE
-----------
Every statement is guarded by an existence check, so running it twice is a
no-op. `--apply` on an already-migrated database reports zero changes.

The new columns are nullable, so MySQL accepts the ALTER on a populated
table without a default and without touching a single existing row. That
is why `server_default` is deliberately NOT used on them: a NOT NULL
column with a server default would rewrite every historical row.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from database import engine  # noqa: E402
from models import Base  # noqa: E402


EVENT_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS restaurant_events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    entity_type VARCHAR(30) NOT NULL,
    entity_id INT NULL,
    actor_user_id INT NULL,
    metadata_json JSON NULL,
    created_at DATETIME NOT NULL,
    INDEX ix_restaurant_events_event_type (event_type),
    INDEX ix_restaurant_events_entity_type (entity_type),
    INDEX ix_restaurant_events_entity_id (entity_id),
    INDEX ix_restaurant_events_actor_user_id (actor_user_id),
    INDEX ix_restaurant_events_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

NEW_COLUMNS = [
    ("order_headers", "status_changed_at", "DATETIME NULL"),
    ("order_headers", "completed_at", "DATETIME NULL"),
    ("order_headers", "paid_at", "DATETIME NULL"),
    ("reservations", "updated_at", "DATETIME NULL"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    planned = []

    if "restaurant_events" in tables:
        print("restaurant_events        already present")
    else:
        planned.append("CREATE TABLE restaurant_events")

    existing_columns = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in ("order_headers", "reservations")
        if table in tables
    }

    for table, column, ddl_type in NEW_COLUMNS:
        if table not in existing_columns:
            print(f"!! {table} is missing - cannot add {column}")
            continue

        if column in existing_columns[table]:
            print(f"{table}.{column:20s} already present")
        else:
            planned.append(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")

    print()
    for step in planned:
        print("  would:", step)

    if not planned:
        print("\nnothing to do - database already has the Phase 6C shape")
        return

    if not args.apply:
        print(f"\ndry run: {len(planned)} change(s). Re-run with --apply")
        return

    with engine.begin() as connection:
        if "restaurant_events" not in tables:
            connection.execute(text(EVENT_TABLE_DDL))
            print("\n  created table restaurant_events")

        for step in planned:
            if not step.startswith("ALTER"):
                continue

            _, _, rest = step.partition("ALTER TABLE ")
            table, _, addition = rest.partition(" ADD COLUMN ")

            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {addition}"))

            print(f"  added {table}.{addition.split()[0]}")

    # The ORM metadata must now describe what the database actually holds,
    # or the first request would fail on a column it believes is missing.
    Base.metadata.create_all(bind=engine, tables=[
        Base.metadata.tables["restaurant_events"],
    ])

    print("\nverification:")
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

        for column in ("status_changed_at", "completed_at", "paid_at"):
            print(f"  order_headers.{column:20s} "
                  f"{'present' if column in columns else 'MISSING'}")

        count = connection.execute(
            text("SELECT COUNT(*) FROM restaurant_events")
        ).scalar()

        print(f"  restaurant_events rows: {count}")

        nulls = connection.execute(
            text(
                "SELECT COUNT(*) FROM order_headers "
                "WHERE status_changed_at IS NOT NULL "
                "OR completed_at IS NOT NULL OR paid_at IS NOT NULL"
            )
        ).scalar()

        print(f"  historical rows backfilled: {nulls} (must be 0)")


if __name__ == "__main__":
    main()