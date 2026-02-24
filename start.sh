#!/bin/bash

# Run database migrations (don't fail startup if migrations error)
python3 -c "
from alembic.config import main
main(argv=['upgrade', 'head'])
" || echo "WARNING: Migration failed, continuing startup..."

# Start the application
exec python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
