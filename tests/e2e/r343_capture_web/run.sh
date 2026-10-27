#!/usr/bin/env bash
# R343 E2E: real Postgres + uvicorn + Chromium (phone viewport) for the mobile capture page.
# Usage: tests/e2e/r343_capture_web/run.sh   (needs node playwright; PLAYWRIGHT_MODULE=/path/to/playwright if not global)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../.." && pwd)
OUT=${E2E_OUT:-$(mktemp -d)}; mkdir -p "$OUT"
export PGPASSWORD=${PEECHA_DB_PASSWORD:-peecha} PEECHA_DB_NAME=peecha_e2e_r343 PEECHA_DB_USER=${PEECHA_DB_USER:-peecha}
export PEECHA_DB_PASSWORD=${PEECHA_DB_PASSWORD:-peecha} PEECHA_DB_HOST=${PEECHA_DB_HOST:-localhost} PEECHA_DB_PORT=${PEECHA_DB_PORT:-5432}
export PYTHONPATH="$ROOT/src" E2E_BASE=http://127.0.0.1:8765
psql -h "$PEECHA_DB_HOST" -U "$PEECHA_DB_USER" -d postgres -qc "DROP DATABASE IF EXISTS peecha_e2e_r343;" -c "CREATE DATABASE peecha_e2e_r343;" 2>/dev/null
python3 "$HERE/setup.py" "$OUT" | tail -1
cd "$ROOT"
python3 -m uvicorn peecha_api.main:app --host 127.0.0.1 --port 8765 > "$OUT/uvicorn.log" 2>&1 &
UV=$!
trap 'kill $UV 2>/dev/null' EXIT
for _ in $(seq 1 40); do curl -s -o /dev/null "$E2E_BASE/health" && break; sleep 0.5; done
node "$HERE/capture_web.js" "$OUT"; BROWSER=$?
python3 "$HERE/verify.py" "$OUT"; VERIFY=$?
kill $UV 2>/dev/null; wait $UV 2>/dev/null
python3 - "$OUT" <<'PY'
import json, sys
s = json.load(open(sys.argv[1] + "/setup.json")); log = open(sys.argv[1] + "/uvicorn.log", encoding="utf-8").read()
ok = s["token"] not in log and s["cancel_token"] not in log
print("OK: tokens never appear in the server log" if ok else "FAIL: token found in server log")
sys.exit(0 if ok else 1)
PY
LOG=$?
echo "screenshots: $OUT"
[ $BROWSER -eq 0 ] && [ $VERIFY -eq 0 ] && [ $LOG -eq 0 ]
