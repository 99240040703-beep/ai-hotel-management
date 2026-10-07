"""
Apply the approved INR menu prices.

Every value below is the price the business signed off. Nothing is
derived from the previous price - these are final intended values, not
an exchange-rate conversion of the old numbers.

Safety:
  * only menu.price is written
  * only the 47 listed ids are touched
  * names, categories, availability, descriptions and every other
    table are left alone
  * the previous prices are printed so the change can be reversed

Usage:
    python scripts/apply_inr_prices.py --dry-run   # show the plan
    python scripts/apply_inr_prices.py --apply
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent),
)

from database import engine  # noqa: E402

from sqlalchemy import text  # noqa: E402


# id -> (name, approved INR price)
APPROVED_INR_PRICES = {
    # Beverages
    37: ("Espresso", 100),
    40: ("Lemonade", 120),
    39: ("Iced Tea", 120),
    36: ("Cappuccino", 150),
    38: ("Latte", 180),
    41: ("Mojito Mocktail", 180),
    45: ("Chocolate Milkshake", 220),
    # Appetizers
    20: ("Garlic Bread", 180),
    21: ("Bruschetta", 240),
    30: ("Mushroom Soup", 240),
    29: ("Minestrone Soup", 220),
    24: ("Greek Salad", 280),
    22: ("Caesar Salad", 300),
    23: ("Caprese Salad", 320),
    42: ("Chicken Wings", 380),
    # Desserts
    35: ("Lemon Sorbet", 180),
    33: ("Chocolate Brownie", 250),
    34: ("Panna Cotta", 280),
    46: ("Apple Pie", 280),
    31: ("Tiramisu", 320),
    32: ("Cheesecake", 340),
    # Biryani
    59: ("Jeera Rice", 150),
    60: ("Veg Fried Rice", 240),
    58: ("Veg Biryani", 280),
    56: ("Egg Biryani", 300),
    57: ("Veg Dum Biryani", 300),
    51: ("Chicken Biryani", 320),
    52: ("Chicken Fried Rice", 320),
    54: ("Mushroom Biryani", 330),
    53: ("Paneer Biryani", 340),
    55: ("Kashmiri Pulao", 350),
    47: ("Hyderabadi Chicken Dum Biryani", 420),
    48: ("Tandoori Chicken Biryani", 450),
    49: ("Mutton Biryani", 560),
    50: ("Hyderabadi Mutton Dum Biryani", 620),
    61: ("Biryani Combo Platter for Two", 680),
    # Mains
    15: ("Margherita Pizza", 280),
    18: ("Veggie Supreme", 320),
    16: ("Pepperoni Pizza", 340),
    17: ("BBQ Chicken Pizza", 380),
    19: ("Four Cheese Pizza", 400),
    43: ("Fish & Chips", 420),
    25: ("Spaghetti Bolognese", 420),
    26: ("Fettuccine Alfredo", 450),
    28: ("Ravioli", 460),
    27: ("Lasagna", 480),
    44: ("Steak Frites", 560),
}


def run(sql, args=None):
    """
    Execute one statement in its own transaction.

    UPDATE/DELETE return no rows, so fetchall() is only valid for a
    SELECT. returns_first_row tells the two apart.
    """
    with engine.begin() as connection:
        result = connection.execute(text(sql), args or {})

        if result.returns_rows:
            return result.fetchall()

        return result.rowcount


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")

    args = parser.parse_args()

    if len(APPROVED_INR_PRICES) != 47:
        raise SystemExit(
            f"expected 47 approved prices, found "
            f"{len(APPROVED_INR_PRICES)}"
        )

    existing = {
        row[0]: (row[1], float(row[2]))
        for row in run("SELECT id, name, price FROM menu")
    }

    missing = [i for i in APPROVED_INR_PRICES if i not in existing]
    unexpected = [i for i in existing if i not in APPROVED_INR_PRICES]

    print("=" * 72)
    print(
        "APPROVED INR PRICES - "
        + ("APPLY" if args.apply else "DRY RUN (no writes)")
    )
    print("=" * 72)

    if unexpected:
        print(
            f"\n  WARNING: {len(unexpected)} menu id(s) are not in the "
            f"approved list and will NOT be touched:"
        )
        for item_id in sorted(unexpected):
            print(f"    id={item_id} {existing[item_id][0]}")

    if missing:
        print(f"\n  ERROR: approved id(s) not found in menu: {missing}")
        raise SystemExit(1)

    # Confirm every approved name matches the database, so a shifted id
    # can never silently reprice the wrong dish.
    mismatched = [
        (i, APPROVED_INR_PRICES[i][0], existing[i][0])
        for i in APPROVED_INR_PRICES
        if existing[i][0] != APPROVED_INR_PRICES[i][0]
    ]

    if mismatched:
        print("\n  ERROR: name mismatch between the approved list and the db:")
        for item_id, want, got in mismatched:
            print(f"    id={item_id} approved='{want}' db='{got}'")
        raise SystemExit(1)

    print("\n  ROLLBACK SNAPSHOT (previous price -> approved price)")
    print(
        f"  {'id':<5}{'item':<38}{'before':>10}{'after':>10}"
    )
    print("  " + "-" * 63)

    changes = []

    for item_id in sorted(APPROVED_INR_PRICES):
        name, target = APPROVED_INR_PRICES[item_id]
        current_name, current_price = existing[item_id]

        marker = "" if current_price == float(target) else "  <-"

        print(
            f"  {item_id:<5}{name[:37]:<38}{current_price:>10.2f}"
            f"{target:>10.2f}{marker}"
        )

        if current_price != float(target):
            changes.append((item_id, current_price))

    print(f"\n  rows needing an update: {len(changes)}")
    print(f"  rows already correct   : {len(APPROVED_INR_PRICES) - len(changes)}")

    if not args.apply:
        print("\n  nothing written. Re-run with --apply.")
        return

    for item_id, _ in changes:
        run(
            "UPDATE menu SET price = :price WHERE id = :id",
            {"price": float(APPROVED_INR_PRICES[item_id][1]), "id": item_id},
        )

    print(f"\n  updated {len(changes)} price(s)")

    # ---- verification: read back and compare against the approved list ----
    print("\n" + "=" * 72)
    print("VERIFICATION")
    print("=" * 72)

    after = {
        row[0]: (row[1], float(row[2]))
        for row in run("SELECT id, name, price FROM menu")
    }

    wrong = []

    for item_id in sorted(APPROVED_INR_PRICES):
        name, target = APPROVED_INR_PRICES[item_id]
        actual_name, actual_price = after[item_id]

        if actual_price != float(target) or actual_name != name:
            wrong.append((item_id, name, target, actual_price))

    print(f"\n  checked {len(APPROVED_INR_PRICES)} items")
    print(f"  mismatches: {len(wrong)}")

    for item_id, name, target, actual in wrong:
        print(f"    id={item_id} {name}: expected {target}, got {actual}")

    if wrong:
        raise SystemExit(1)

    print("\n  every approved price matches the database exactly")

    untouched = run(
        "SELECT COUNT(*) FROM menu WHERE price IN (2.49, 2.69, 2.79, 2.99, "
        "3.49, 3.99, 4.49, 4.79, 4.99, 5.29, 5.49, 5.79, 5.99, 6.49, 6.99, "
        "8.99, 9.49, 9.99, 10.49, 10.99, 11.49, 11.99, 12.49, 12.79, 13.99, "
        "14.99, 15.49, 15.99, 16.99, 18.99, 19.99, 24.99, 26.99, 27.99)"
    )[0][0]

    print(
        f"  menu rows still holding an old-scale price: {untouched}"
        + ("  (expected 0)" if untouched == 0 else "  <- investigate")
    )


if __name__ == "__main__":
    main()