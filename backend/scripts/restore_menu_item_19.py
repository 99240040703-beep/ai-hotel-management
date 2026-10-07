"""
Restore the one approved menu row that went missing: id 19,
'Four Cheese Pizza'.

Why this is a restore and not a new dish
----------------------------------------
Phase 2.5 established the approved INR menu as exactly 47 rows, ids
15-61, with a fixed price for each. That set is the restaurant's real
menu, and id 19 is part of it. A row disappearing from it is data loss,
not a test artifact, so it is put back with the values Phase 2.5 approved
rather than left absent.

The script is safe to run repeatedly: it inserts the row only if id 19 is
absent, and refuses to overwrite anything that is already there.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from database import engine  # noqa: E402


# The Phase 2.5 approved figure for id 19.
APPROVED = {
    "id": 19,
    "name": "Four Cheese Pizza",
    "category": "Main",
    "price": 400.00,
    # A cheese pizza, so vegetarian, matching the pizzas either side of it.
    "is_vegetarian": 1,
    "available": 1,
    "is_featured": 0,
    "spice_level": 0,
    "prep_time": 15,
}


def main():
    with engine.connect() as connection:
        existing = connection.execute(
            text("SELECT id, name, category, price FROM menu WHERE id = :i"),
            {"i": APPROVED["id"]},
        ).first()

        if existing:
            print(f"menu {APPROVED['id']} is present: {existing}")
            print("nothing to do")
            return

        connection.execute(
            text(
                "INSERT INTO menu (id, name, category, price, available, "
                "is_vegetarian, is_featured, spice_level, prep_time) "
                "VALUES (:id, :name, :category, :price, :available, "
                ":veg, :featured, :spice, :prep)"
            ),
            {
                "id": APPROVED["id"],
                "name": APPROVED["name"],
                "category": APPROVED["category"],
                "price": APPROVED["price"],
                "available": APPROVED["available"],
                "veg": APPROVED["is_vegetarian"],
                "featured": APPROVED["is_featured"],
                "spice": APPROVED["spice_level"],
                "prep": APPROVED["prep_time"],
            },
        )

        connection.commit()

        print(
            f"restored menu {APPROVED['id']} {APPROVED['name']} "
            f"at Rs.{APPROVED['price']:.2f}"
        )

    with engine.connect() as connection:
        for row in connection.execute(
            text("SELECT COUNT(*), MIN(id), MAX(id) FROM menu")
        ):
            print(f"menu rows={row[0]} id range={row[1]}..{row[2]}")

        print(
            "rows outside the approved range:",
            connection.execute(
                text("SELECT id, name FROM menu WHERE id < 15 OR id > 61")
            ).fetchall(),
        )


if __name__ == "__main__":
    main()