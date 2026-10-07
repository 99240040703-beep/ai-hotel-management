"""
Identity backfill - Phase 1.

Links the authenticated `users` table to the CRM `customers` table, and
attaches historical rows to the account that owns them:

    users.customer_id            -> customers.id
    orders.user_id               -> users.id
    reviews.user_id              -> users.id
    reservations.user_id         -> users.id

SAFETY RULES
------------
* Nothing is deleted.
* No user account is ever created. Accounts are only ever *read*.
  A historical customer with no login simply stays unlinked and is
  reported, because inventing an account would mean guessing a
  password.
* Ownership is decided by user_id once a row has one. customer_name is
  only used to find a first owner.
* Default mode is DRY RUN. Pass --apply to write.

Usage
-----
    python scripts/backfill_identity.py            # dry run, writes nothing
    python scripts/backfill_identity.py --apply    # perform the backfill

Run it from the backend directory so it picks up backend/.env.
"""

import argparse
import os
import sys
from pathlib import Path

# Make sure the backend package modules are importable.
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent),
)

from database import SessionLocal  # noqa: E402
from models import (  # noqa: E402
    Customer,
    Order,
    Reservation,
    Review,
    User,
)


def _normalise(value):
    """Case/space-insensitive key used for matching display names."""
    if value is None:
        return None

    cleaned = " ".join(str(value).split()).strip().lower()

    return cleaned or None


def build_customer_indexes(db):
    """
    Two independent indexes over the CRM table.

    A name that maps to more than one customer is recorded as ambiguous
    and is never used for a link.
    """
    by_name = {}
    by_email = {}
    ambiguous_names = set()

    for customer in db.query(Customer).all():
        name_key = _normalise(customer.name)
        email_key = _normalise(customer.email)

        if name_key:
            by_name.setdefault(name_key, []).append(customer)

        if email_key:
            by_email.setdefault(email_key, []).append(customer)

    for name_key, matches in by_name.items():
        if len(matches) > 1:
            ambiguous_names.add(name_key)

    return by_name, by_email, ambiguous_names


def report_header(apply_changes):
    mode = "APPLY (writes to the database)" if apply_changes else "DRY RUN (no writes)"

    print("=" * 74)
    print(f"IDENTITY BACKFILL - {mode}")
    print("=" * 74)


def plan_user_links(db, apply_changes):
    """Propose users.customer_id for every account."""
    by_name, by_email, ambiguous_names = build_customer_indexes(db)

    users = db.query(User).all()

    print("\n" + "-" * 74)
    print("STEP 1  users.customer_id  (login account -> CRM customer)")
    print("-" * 74)

    planned = []
    unlinked = []
    skipped = []

    print(f"\n  {'id':<4}{'name':<22}{'role':<11}{'customer_id':<13}basis")
    print(f"  {'-' * 4}{'-' * 22}{'-' * 11}{'-' * 13}{'-' * 30}")

    for user in users:
        name_key = _normalise(user.name)
        email_key = _normalise(user.email)

        if user.customer_id:
            print(
                f"  {user.id:<4}{user.name[:21]:<22}{user.role:<11}"
                f"{str(user.customer_id):<13}already linked - left alone"
            )
            skipped.append(user)
            continue

        match = None
        basis = ""

        if email_key and email_key in by_email:
            candidates = by_email[email_key]

            if len(candidates) == 1:
                match = candidates[0]
                basis = "exact email match"
        elif name_key and name_key in by_name:
            candidates = by_name[name_key]

            if len(candidates) == 1:
                match = candidates[0]
                basis = "exact name match"
            else:
                basis = f"AMBIGUOUS: {len(candidates)} customers share this name"

        if match is None:
            print(
                f"  {user.id:<4}{user.name[:21]:<22}{user.role:<11}"
                f"{'-':<13}{basis or 'no CRM customer with this name or email'}"
            )
            unlinked.append((user, basis))
            continue

        print(
            f"  {user.id:<4}{user.name[:21]:<22}{user.role:<11}"
            f"{str(match.id):<13}{basis}"
        )

        planned.append((user, match))

    if apply_changes and planned:
        for user, customer in planned:
            user.customer_id = customer.id

        db.commit()
        print(f"\n  -> wrote users.customer_id for {len(planned)} account(s)")
    else:
        print(f"\n  -> would write users.customer_id for {len(planned)} account(s)")

    print(f"  -> already linked (untouched): {len(skipped)}")
    print(f"  -> no safe match: {len(unlinked)}")

    return planned, unlinked


def plan_row_links(db, model, label, apply_changes):
    """
    Attach historical rows to a login account.

    Only rows whose customer_name matches the display name of an
    EXISTING user are linked. Rows belonging to a CRM customer who has
    never signed in are reported as unlinkable, because linking them
    would require inventing an account.
    """
    print("\n" + "-" * 74)
    print(f"STEP {label}  {model.__tablename__}.user_id  (history -> account)")
    print("-" * 74)

    users = db.query(User).all()

    # display name (normalised) -> list of users claiming that name
    name_to_users = {}

    for user in users:
        key = _normalise(user.name)

        if key:
            name_to_users.setdefault(key, []).append(user)

    ambiguous = {
        key for key, matches in name_to_users.items() if len(matches) > 1
    }

    total = db.query(model).count()
    already = db.query(model).filter(model.user_id.isnot(None)).count()
    pending = total - already

    candidates = []

    for row in db.query(model).filter(model.user_id.is_(None)).all():
        key = _normalise(getattr(row, "customer_name", None))

        if not key:
            continue

        if key in ambiguous:
            continue

        matches = name_to_users.get(key) or []

        # Admins must never inherit a customer's order history.
        customer_matches = [
            user for user in matches if user.role == "customer"
        ]

        if len(customer_matches) == 1:
            candidates.append((row, customer_matches[0]))

    grouped = {}

    for row, user in candidates:
        grouped.setdefault(user.name, {"rows": 0, "model": label})

        grouped[user.name]["rows"] += 1

    if grouped:
        print(f"\n  linkable through an existing login account:")

        for name, info in sorted(grouped.items()):
            print(f"    {name:<24}{info['rows']:>5} row(s) -> users.customer_name")

    unlinkable_names = {}

    for row in db.query(model).filter(model.user_id.is_(None)).all():
        if any(row is candidate for candidate, _ in candidates):
            continue

        key = getattr(row, "customer_name", None) or "(blank)"

        unlinkable_names[key] = unlinkable_names.get(key, 0) + 1

    if unlinkable_names:
        print(f"\n  NOT linkable (no login account owns this name):")

        for name, count in sorted(
            unlinkable_names.items(), key=lambda pair: -pair[1]
        ):
            print(f"    {name:<24}{count:>5} row(s) - left as customer_name only")

    print(
        f"\n  total rows: {total}   already linked: {already}   "
        f"pending: {pending}"
    )

    if apply_changes and candidates:
        for row, user in candidates:
            row.user_id = user.id

        db.commit()

        print(f"  -> wrote user_id for {len(candidates)} row(s)")
    else:
        print(f"  -> would write user_id for {len(candidates)} row(s)")

    return len(candidates), unlinkable_names


def show_orphans(db):
    """Flag names that exist in the data but have no login at all."""
    print("\n" + "-" * 74)
    print("ORPHANED IDENTITIES  (present in data, no login account)")
    print("-" * 74)

    users = db.query(User).all()

    known = {_normalise(user.name) for user in users}

    for model, label in (
        (Order, "orders"),
        (Review, "reviews"),
        (Reservation, "reservations"),
    ):
        seen = {}

        for row in db.query(model).all():
            key = getattr(row, "customer_name", None)

            if not key:
                continue

            seen[key] = seen.get(key, 0) + 1

        orphans = {
            name: count
            for name, count in seen.items()
            if _normalise(name) not in known
        }

        if orphans:
            print(f"\n  {label}:")

            for name, count in sorted(
                orphans.items(), key=lambda pair: -pair[1]
            ):
                print(f"    {name:<24}{count:>5} row(s) - no matching users row")

    print(
        "\n  These rows keep working: the customer screens fall back to\n"
        "  customer_name when a row has no user_id. They become\n"
        "  attributable only after an admin creates a real login for\n"
        "  that person - this script will not guess a password."
    )


def main():
    parser = argparse.ArgumentParser(
        description="Link users, customers and historical rows (dry run by default).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the changes. Omit for a dry run.",
    )

    args = parser.parse_args()

    apply_changes = args.apply

    report_header(apply_changes)

    db = SessionLocal()

    try:
        plan_user_links(db, apply_changes)

        plan_row_links(db, Order, "2", apply_changes)
        plan_row_links(db, Review, "3", apply_changes)
        plan_row_links(db, Reservation, "4", apply_changes)

        show_orphans(db)

        print("\n" + "=" * 74)

        if apply_changes:
            print("Backfill complete. No records were deleted or created.")

        else:
            print(
                "DRY RUN finished - nothing was written.\n"
                "Re-run with --apply to perform exactly these changes."
            )

        print("=" * 74)
    finally:
        db.close()


if __name__ == "__main__":
    main()
