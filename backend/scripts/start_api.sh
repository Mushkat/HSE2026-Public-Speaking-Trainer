#!/usr/bin/env sh
set -eu

echo "[startup] waiting for dependencies"
python /app/scripts/wait_for_services.py
echo "[startup] resolved database target"
python /app/scripts/print_db_info.py
echo "[startup] applying alembic migrations"
python /app/scripts/run_migrations.py
echo "[startup] verifying migrated schema"
/app/scripts/verify_db.sh
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
