#!/bin/sh
# Daily job: refresh the last 7 days of every report in restosuite.db and export/*.csv.
# Re-pulling a week catches refunds and edits made after the day closed.
# Extra arguments are passed on, e.g. deploy/run-daily.sh --days 30
set -eu
cd "$(dirname "$0")/.."
exec flock -n /tmp/restosuite-export.lock \
    .venv/bin/python export_all.py --days 7 --csv-dir export "$@"
