#!/usr/bin/env bash
# Integration tests against a live local PostgreSQL (user/pass peecha/peecha).
# Usage: tests/integration/run_all.sh [pattern]   e.g.  run_all.sh r209
# Scripts sharing a PEECHA_DB_NAME form one group: the DB is recreated once
# per group and the group runs in filename order (later scripts reuse the
# data of earlier ones, e.g. r161_*, r173_*).
set -u
shopt -s nullglob
cd "$(dirname "$0")"
export PGPASSWORD=peecha
pattern="${1:-}"
failures=0

declare -A groups
for f in test_*${pattern}*.py; do
  db=$(grep -oP 'PEECHA_DB_NAME"\] = "\K[^"]+' "$f")
  groups[$db]+="$f "
done

for db in $(printf '%s\n' "${!groups[@]}" | sort); do
  psql -h localhost -U peecha -d postgres -qc "DROP DATABASE IF EXISTS $db;" -c "CREATE DATABASE $db;" >/dev/null 2>&1
  for f in $(printf '%s\n' ${groups[$db]} | sort); do
    result=$(python3 "$f" 2>&1 | tail -1)
    if [[ "$result" == *"ALL PASS"* ]]; then
      echo "PASS  $f"
    elif python3 -c "import sys; sys.exit(0 if 'check(' not in open('$f').read() else 1)"; then
      echo "RUN   $f (no assertions)"
    else
      echo "FAIL  $f: $result"
      failures=$((failures + 1))
    fi
  done
done
echo "failures: $failures"
exit $failures
