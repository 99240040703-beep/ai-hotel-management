"""
Phase 1 schema repair: users.active.

`active` was added to an existing table by migrations.py, which renders
a python-side default. MySQL fills NOT NULL columns on ALTER TABLE with
the *type* default (0), not the application default, so every account
already in the table came out deactivated.

This script:
  1. gives the column a SQL-level DEFAULT 1, so rows inserted without
     an explicit value are active
  2. sets existing rows to active

It is safe to re-run. Nothing is deleted.

    python scripts/fix_users_active.py --dry-run
    python scripts/fix_users_active.py
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    # Every statement runs in its own short transaction. A long-lived
    # read session would hold a shared lock on `users` and the ALTER
    # would then block against itself.
    def run(sql):
        with engine.begin() as connection:
            return connection.execute(text(sql))

    rows = run("SELECT id, name, active FROM users ORDER BY id").fetchall()

    inactive = [row for row in rows if not row[2]]

    print(f"users.active repair ({'DRY RUN' if args.dry_run else 'APPLY'})")
    print(f"  total accounts        : {len(rows)}")
    print(f"  currently active      : {len(rows) - len(inactive)}")
    print(f"  currently INACTIVE    : {len(inactive)}")

    for row in inactive:
        print(f"    id={row[0]} name={row[1]} active={row[2]}")

    if not inactive:
        print("\n  nothing to repair - every account is already active")
        return

    if args.dry_run:
        print("\n  would set active = 1 for those accounts")
        return

    run("ALTER TABLE users ALTER COLUMN active SET DEFAULT 1")
    run("UPDATE users SET active = 1 WHERE active = 0")

    after = run("SELECT id, name, active FROM users ORDER BY id").fetchall()

    print("\n  after repair:")
    for row in after:
        print(f"    id={row[0]} name={row[1]} active={row[2]}")


if __name__ == "__main__":
    main()
