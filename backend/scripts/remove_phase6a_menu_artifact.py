"""
Phase 6A - remove one isolated menu test artifact.

    python scripts/remove_phase6a_menu_artifact.py            # dry run
    python scripts/remove_phase6a_menu_artifact.py --apply

Why this exists
---------------
The Phase 2.5 approved INR menu is 47 rows, ids 15-61. A 48th row sits
past the end of that set:

    id 62  name 'samosa'  category 'Appetizer'  price 50.00
           is_featured 1, no description

Evidence that it is a probe row and not menu data:

  * The name is lower-case and generic, unlike every seeded dish.
  * 50.00 sits on the pre-INR price scale that Phase 2.5 removed, and is
    below the cheapest real dish (Rs.100).
  * No order row references it. The 50 seeded orders named 'Veg Samosa'
    are a different dish name, and 'Veg Samosa' is not on the menu.
  * No review references it. Both samosa reviews name 'Veg Samosa'.
  * No table in the schema has a menu_id column, so nothing can point at
    menu.id = 62 as a foreign key.

This script refuses to delete the row if any order or review does name
it, so it cannot silently remove something real. It never touches any
other menu row, and it never touches an order.

It does NOT touch historical orders. The two known Phase 5 scaffold
rows (Rs.8.99 and Rs.13.99) stay exactly as they are; Phase 6A reports
them through /api/analytics/overview -> all_time.data_quality instead of
rewriting or deleting them.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from database import engine  # noqa: E402


ARTIFACT_ID = 62
ARTIFACT_NAME = "samosa"


def run(sql, args=None):
    with engine.begin() as connection:
        result = connection.execute(text(sql), args or {})

        return result.fetchall() if result.returns_rows else result.rowcount


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rows = run(
        "SELECT id, name, category, price, available, is_featured, description "
        "FROM menu WHERE id = :i OR LOWER(name) = :n",
        {"i": ARTIFACT_ID, "n": ARTIFACT_NAME},
    )

    if not rows:
        print("no artifact row present - nothing to do")
        return

    print("candidate rows:")
    for row in rows:
        print("  ", row)

    menu_id = rows[0][0]

    orders = run(
        "SELECT COUNT(*) FROM orders WHERE menu_item = :n",
        {"n": ARTIFACT_NAME},
    )[0][0]
    reviews = run(
        "SELECT COUNT(*) FROM reviews WHERE menu_item = :n",
        {"n": ARTIFACT_NAME},
    )[0][0]

    print(f"\n  orders naming it   : {orders}")
    print(f"  reviews naming it  : {reviews}")

    if orders or reviews:
        print(
            "\n  REFUSING to delete: real orders or reviews name this dish, "
            "so it is menu data rather than a probe row."
        )
        return

    approved = run("SELECT COUNT(*) FROM menu WHERE id BETWEEN 15 AND 61")[0][0]
    print(f"  approved Phase 2.5 rows (id 15-61): {approved}")

    if not args.apply:
        print("\n  dry run - re-run with --apply")
        return

    removed = run("DELETE FROM menu WHERE id = :i", {"i": menu_id})
    print(f"\n  removed menu rows: {removed}")
    print(f"  menu rows now   : {run('SELECT COUNT(*) FROM menu')[0][0]}")


if __name__ == "__main__":
    main()