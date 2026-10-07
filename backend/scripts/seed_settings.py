"""
Seed the `settings` table with a documented default configuration.

The table ships empty, which previously meant tax and currency had no
source of truth and the frontend applied a hardcoded 5% GST. Checkout
now reads these values instead, so the row has to exist.

Run from the backend directory:

    python scripts/seed_settings.py            # dry run, prints the plan
    python scripts/seed_settings.py --apply

Nothing is overwritten unless --apply is passed, and an existing row is
left exactly as it is.

DEFAULTS AND WHY
----------------
tax_percentage = 5.0
    Matches the 5% GST the customer interface has always displayed, so
    enabling server-side tax does not silently change any bill. Change
    it here if the real rate differs.

service_charge_percentage = 0.0
    The restaurant does not currently add a service charge.

currency = "UNSET"
    DELIBERATELY NOT SET TO INR. The menu currently holds prices on an
    unreconciled scale (2.49 - 27.99) that the interface renders with a
    rupee sign. Choosing the currency and rescaling the menu prices is a
    business decision that has not been made yet, so no currency is
    asserted here. Until it is, every checkout response carries
    currency "UNSET" plus a warning, and the admin Settings screen shows
    the same value. To finalise:

        UPDATE settings SET currency = 'INR' WHERE id = 1;

    and rescale menu.price in the same change so the two agree.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent),
)

from database import SessionLocal  # noqa: E402
from models import Settings  # noqa: E402


DEFAULTS = {
    "restaurant_name": "Paradise Restaurant",
    "restaurant_address": "Main Street",
    "phone": "",
    "email": "",
    # See the module docstring before changing this.
    "currency": "UNSET",
    "tax_percentage": 5.0,
    "service_charge_percentage": 0.0,
    "opening_time": "10:00",
    "closing_time": "23:00",
    "notifications_enabled": True,
    "ai_enabled": True,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")

    args = parser.parse_args()

    db = SessionLocal()

    try:
        existing = db.query(Settings).first()

        if existing:
            print("settings row already exists - nothing to do.")
            print(f"  id                : {existing.id}")
            print(f"  currency          : {existing.currency}")
            print(f"  tax_percentage    : {existing.tax_percentage}")
            print(
                "  service_charge_pct: "
                f"{existing.service_charge_percentage}"
            )

            return

        print(f"settings is empty. Plan ({'APPLY' if args.apply else 'DRY RUN'}):")
        print(f"  {'field':<28}{'value'}")
        print(f"  {'-' * 28}{'-' * 24}")

        for field, value in DEFAULTS.items():
            print(f"  {field:<28}{value}")

        if not args.apply:
            print("\n  nothing written. Re-run with --apply to insert.")
            return

        row = Settings(**DEFAULTS)

        db.add(row)
        db.commit()
        db.refresh(row)

        print(f"\n  inserted settings id={row.id}")
        print(f"  checkout will now apply {row.tax_percentage}% tax")
        print(f"  currency is '{row.currency}' - set it once prices are agreed")
    finally:
        db.close()


if __name__ == "__main__":
    main()
