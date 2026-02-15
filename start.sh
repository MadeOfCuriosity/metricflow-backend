#!/bin/bash
set -e

# Run database migrations
python3 -c "
from alembic.config import main
main(argv=['upgrade', 'head'])
"

# Start the application
exec python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
