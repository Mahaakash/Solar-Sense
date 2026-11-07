"""
scripts/migrate_sqlite_to_postgres.py
─────────────────────────────────────
Copy all rows from the local SQLite database to a remote Postgres database.
Preserves primary-key IDs. Refuses to run if target tables already contain data
unless --force is passed.

Usage:
    DATABASE_URL=postgresql://user:pass@host:5432/db python \\
        scripts/migrate_sqlite_to_postgres.py
    DATABASE_URL=postgresql://user:pass@host:5432/db python \\
        scripts/migrate_sqlite_to_postgres.py --force
"""

import argparse
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add project root to path so backend imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import DATABASE_URL
from backend.db import Alert, Base, DailyReading, Site, User, normalise_database_url

LOCAL_SQLITE_PATH = "data/solarsense.db"

TABLE_ORDER = [
    ("users", User),
    ("sites", Site),
    ("daily_readings", DailyReading),
    ("alerts", Alert),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate SolarSense data from SQLite to Postgres.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Truncate target tables before copying (DESTRUCTIVE).",
    )
    args = parser.parse_args()

    # 1. Validate source
    if not Path(LOCAL_SQLITE_PATH).exists():
        print(f"ERROR: Local SQLite database not found at '{LOCAL_SQLITE_PATH}'.")
        sys.exit(1)

    # 2. Validate target
    target_url = normalise_database_url(DATABASE_URL)
    if target_url.startswith("sqlite"):
        print("ERROR: DATABASE_URL points to SQLite. Set it to a Postgres connection string.")
        sys.exit(1)

    print(f"Source: {LOCAL_SQLITE_PATH}")
    print(f"Target: {target_url.split('@')[-1] if '@' in target_url else '(hidden)'}")
    print()

    # 3. Connect to source SQLite
    src_conn = sqlite3.connect(LOCAL_SQLITE_PATH)
    src_conn.row_factory = sqlite3.Row

    # 4. Connect to target Postgres
    target_engine = create_engine(target_url, pool_pre_ping=True)
    Base.metadata.create_all(bind=target_engine)
    TargetSession = sessionmaker(bind=target_engine, expire_on_commit=False)

    with TargetSession() as session:
        # 5. Check for existing data
        if not args.force:
            for table_name, model in TABLE_ORDER:
                count = session.query(model).count()
                if count > 0:
                    print(
                        f"ERROR: Target table '{table_name}' already contains {count} rows. "
                        "Use --force to truncate and overwrite."
                    )
                    src_conn.close()
                    sys.exit(1)
        else:
            # Truncate in reverse order to respect FK constraints
            for table_name, _ in reversed(TABLE_ORDER):
                session.execute(text(f"TRUNCATE TABLE {table_name} CASCADE"))
            session.commit()
            print("Target tables truncated (--force).")

        # 6. Copy data table by table
        for table_name, model in TABLE_ORDER:
            cursor = src_conn.cursor()
            cursor.execute(f"SELECT * FROM {table_name}")
            rows = cursor.fetchall()

            if not rows:
                print(f"  {table_name}: 0 rows (empty)")
                continue

            columns = [desc[0] for desc in cursor.description]
            inserted = 0
            for row in rows:
                row_dict = dict(zip(columns, row, strict=False))
                obj = model(**row_dict)
                session.add(obj)
                inserted += 1

            session.flush()
            print(f"  {table_name}: {inserted} rows copied")

        session.commit()

    src_conn.close()
    print("\nMigration complete!")


if __name__ == "__main__":
    main()
