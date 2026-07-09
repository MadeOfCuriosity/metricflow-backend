#!/bin/bash
set -e

# Run database migrations under an advisory lock (scripts/run_migrations.py).
# Fatal on failure: booting against a schema that failed to migrate is
# worse than not booting at all.
python3 scripts/run_migrations.py

# Start the application
exec python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
