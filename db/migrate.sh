#!/bin/sh
set -e

log() { printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"; }

PGHOST="${POSTGRES_HOST:-db}"
PGPORT="${POSTGRES_PORT:-5432}"
PGDATABASE="${POSTGRES_DB:?POSTGRES_DB is required}"
PGUSER="${POSTGRES_USER:?POSTGRES_USER is required}"
PGPASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
export PGPASSWORD

MIGRATIONS_DIR="${MIGRATIONS_DIR:-/migrations}"

log "Waiting for Postgres at ${PGHOST}:${PGPORT}/${PGDATABASE} ..."
i=0
until pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" >/dev/null 2>&1; do
  i=$((i+1))
  [ "$i" -gt 60 ] && { log "Postgres is not ready after 60s — abort."; exit 1; }
  sleep 1
done
log "Postgres is ready."

psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS public.schema_migrations (
  id SERIAL PRIMARY KEY,
  filename TEXT UNIQUE NOT NULL,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
SQL

MIG_LIST=$(find "$MIGRATIONS_DIR" -maxdepth 1 -type f -name '*.sql' 2>/dev/null | sort)

applied_any="false"
for f in $MIG_LIST; do
  fname=$(basename "$f")
  exists=$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -t -A -c "SELECT 1 FROM public.schema_migrations WHERE filename='$fname' LIMIT 1;" || true)
  [ "$exists" = "1" ] && { log "Skip $fname (already applied)"; continue; }
  log "Applying $fname ..."
  psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1 -f "$f"
  psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -v ON_ERROR_STOP=1 -c "INSERT INTO public.schema_migrations (filename) VALUES ('$fname');"
  log "Done $fname."
  applied_any="true"
done

[ "$applied_any" = "true" ] && log "All migrations applied." || log "No new migrations to apply."
