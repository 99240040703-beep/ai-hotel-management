"""
Create the restaurant's starting tables.

Every table gets its own random qr_token, which is what the printed QR
encodes. Re-running does not disturb existing tables.

    python scripts/seed_tables.py              # show the plan
    python scripts/seed_tables.py --apply

Adjust the layout below to match the real dining room. Once the QR
stickers are printed, use POST /api/tables/{id}/regenerate-qr to roll a
single table without reprinting the rest.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent),
)

from database import SessionLocal  # noqa: E402
from models import RestaurantTable  # noqa: E402
from services.table_service import (  # noqa: E402
    assign_token_if_missing,
)


# table_number, table_name, capacity, section
DEFAULT_LAYOUT = [
    (1, "Table 1", 4, "Dining Room"),
    (2, "Table 2", 4, "Dining Room"),
    (3, "Table 3", 4, "Dining Room"),
    (4, "Table 4", 6, "Dining Room"),
    (5, "Table 5", 6, "Dining Room"),
    (6, "Table 6", 2, "Dining Room"),
    (7, "Table 7", 2, "Dining Room"),
    (8, "Table 8", 2, "Dining Room"),
    (9, "Table 9", 4, "Dining Room"),
    (10, "Table 10", 4, "Terrace"),
    (11, "Table 11", 6, "Terrace"),
    (12, "Table 12", 8, "Private Room"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")

    args = parser.parse_args()

    db = SessionLocal()

    try:
        existing = {
            row.table_number: row
            for row in db.query(RestaurantTable).all()
        }

        print(
            "tables seed "
            + ("(APPLY)" if args.apply else "(DRY RUN - no writes)")
        )
        print(
            f"\n  {'num':<5}{'name':<12}{'cap':<5}{'section':<14}"
            f"{'exists':<9}{'token'}"
        )
        print("  " + "-" * 70)

        created = 0

        for number, name, capacity, section in DEFAULT_LAYOUT:
            row = existing.get(number)

            if row:
                # An existing table keeps its token, so a printed QR
                # stays valid.
                print(
                    f"  {number:<5}{str(row.table_name):<12}"
                    f"{row.capacity:<5}{str(row.section):<14}"
                    f"{'yes':<9}{(row.qr_token or '')[:16]}..."
                )
                continue

            print(
                f"  {number:<5}{name:<12}{capacity:<5}{section:<14}"
                f"{'-':<9}will be generated"
            )

            if not args.apply:
                continue

            table = RestaurantTable(
                table_number=number,
                table_name=name,
                capacity=capacity,
                section=section,
                is_active=True,
            )

            assign_token_if_missing(db, table)

            db.add(table)
            created += 1

        if args.apply and created:
            db.commit()
            print(f"\n  created {created} table(s)")

            print("\n  resulting tokens:")
            for row in (
                db.query(RestaurantTable)
                .order_by(RestaurantTable.table_number)
                .all()
            ):
                print(f"    table {row.table_number:<4} {row.qr_token}")
        elif not args.apply:
            print("\n  nothing written. Re-run with --apply.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
