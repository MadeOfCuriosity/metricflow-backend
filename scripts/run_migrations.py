"""Run Alembic migrations under a Postgres advisory lock.

App Runner can scale to many concurrent container instances, and each
instance boots independently. Without a lock, multiple instances booting
at once would all run `alembic upgrade head` against the same database
simultaneously. The advisory lock serializes them: whichever instance
gets there first holds the lock for the duration of the upgrade, and the
rest block until it's done (at which point Alembic sees the schema is
already current and is a no-op).

Exits non-zero on failure — the caller (start.sh) is expected to treat
that as fatal rather than continuing to boot against a stale schema.
"""

import os
import sys

import psycopg2
from alembic import command
from alembic.config import Config

# Arbitrary fixed key, scoped to this app. Any two processes calling
# pg_advisory_lock with the same key serialize against each other.
MIGRATION_LOCK_KEY = 823746192


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(database_url)
    conn.autocommit = True
    cur = conn.cursor()
    try:
        cur.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
    finally:
        cur.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))
        cur.close()
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FATAL: migration failed: {exc}", file=sys.stderr)
        sys.exit(1)
