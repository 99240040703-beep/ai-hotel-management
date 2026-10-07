"""
Lightweight schema migrations.

SQLAlchemy's create_all() only creates missing tables - it never adds
columns to a table that already exists. This module walks the models and
issues ALTER TABLE ... ADD COLUMN for every mapped column that the live
database does not have yet, so an existing installation keeps working
after new fields are added to models.py.

Run automatically from main.py on startup, or manually:

    python migrations.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateColumn

from database import Base, engine

import models  # noqa: F401  (registers every table on Base.metadata)


# Columns that must never be added by this helper
# because they are primary keys.
SKIP_COLUMNS = {"id"}


def apply_missing_columns() -> list:
    """
    Adds any mapped column that is missing from the live database.

    Returns a list of human readable descriptions of what changed.
    """
    inspector = inspect(engine)

    existing_tables = set(inspector.get_table_names())

    applied = []

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue

        existing_columns = {
            col["name"] for col in inspector.get_columns(table.name)
        }

        for column in table.columns:
            if column.name in existing_columns:
                continue

            if column.name in SKIP_COLUMNS:
                continue

            # CreateColumn renders the type, NOT NULL flag and a properly
            # quoted DEFAULT for the active dialect.
            ddl = str(
                CreateColumn(column).compile(dialect=engine.dialect)
            ).strip()

            statement = text(f"ALTER TABLE {table.name} ADD COLUMN {ddl}")

            with engine.begin() as connection:
                connection.execute(statement)

            applied.append(f"{table.name}.{column.name}")

    return applied


if __name__ == "__main__":
    changes = apply_missing_columns()

    if changes:
        print("Added missing columns:")
        for change in changes:
            print(f"  - {change}")
    else:
        print("Database schema is already up to date.")