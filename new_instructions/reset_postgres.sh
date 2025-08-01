#!/usr/bin/env bash
# reset_postgres.sh — hard-reset a Homebrew Postgres@14 installation
set -euo pipefail

# ─────────── Configuration ───────────
PG_MAJOR=14
PG_PREFIX="/opt/homebrew/opt/postgresql@${PG_MAJOR}"
DATA_DIR="/opt/homebrew/var/postgresql@${PG_MAJOR}"
BIN_DIR="${PG_PREFIX}/bin"

PG_USER="postgres"     # superuser role to ensure exists
PG_DB="buckaroo_db"    # database to create
PG_PASS="secret"       # password for the superuser

PORT=5432              # change if you need a different port
LOG_FILE="${DATA_DIR}/server.log"

# ─────────── Helper that runs a Postgres binary ───────────
pg() { "${BIN_DIR}/$1" "${@:2}"; }

echo "Stopping any running ${BIN_DIR}/postgres owned by $(whoami) …"
pgrep -u "$(whoami)" -f "${BIN_DIR}/postgres" && \
    pkill -u "$(whoami)" -f "${BIN_DIR}/postgres" || true
# If you use brew-services:  brew services stop postgresql@${PG_MAJOR}

echo "Removing old cluster at ${DATA_DIR} …"
rm -rf "${DATA_DIR}"
mkdir -p "${DATA_DIR}"
chmod 700 "${DATA_DIR}"        # avoid FATAL “has group or world access”

echo "Initialising new cluster …"
pg initdb -D "${DATA_DIR}" \
          --username="${PG_USER}" \
          --auth-local=trust --auth-host=trust

echo "Starting temporary server on port ${PORT} …"
if ! pg pg_ctl -D "${DATA_DIR}" -l "${LOG_FILE}" -o "-p ${PORT}" start ; then
    echo "Postgres failed to start. Last 40 log lines:"
    tail -n 40 "${LOG_FILE}"
    exit 1
fi

# Wait until the server is truly ready
until pg pg_isready -q -p "${PORT}"; do sleep 0.5; done

echo "Ensuring superuser '${PG_USER}' exists …"
pg createuser -s -p "${PORT}" "${PG_USER}" 2>/dev/null || true

echo "Setting password for '${PG_USER}' …"
pg psql -U "${PG_USER}" -p "${PORT}" -d postgres \
        -c "ALTER ROLE ${PG_USER} PASSWORD '${PG_PASS}';"

echo "Creating database '${PG_DB}' …"
pg createdb -U "${PG_USER}" -p "${PORT}" "${PG_DB}" 2>/dev/null || true

echo "Stopping temporary server …"
pg pg_ctl -D "${DATA_DIR}" stop -m fast

echo "Done!  Cluster reset and shut down."
echo
echo "To start Postgres manually later, run:"
echo "  '${BIN_DIR}/pg_ctl' -D '${DATA_DIR}' -l '${LOG_FILE}' -o \"-p ${PORT}\" start"
echo "or manage it via Homebrew services:"
echo "  brew services start postgresql@${PG_MAJOR}"
