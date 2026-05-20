#!/usr/bin/env bash
# Smoke-test the /internal-api/* trio that the /mempool-summary page
# drives in the browser. Exercises the empty-mempool path that used to
# crash with `TypeError: Cannot set properties of undefined (setting
# 'buckets')` before the install.sh defensive patch.
export LC_ALL=C
set -uo pipefail
trap '' PIPE

ID=$(tr -dc a-z0-9 </dev/urandom | head -c 5)
BASE=http://127.0.0.1:3002

echo "=== build-mempool-summary (statusId=$ID) ==="
curl -s -o /tmp/build.json -w 'HTTP=%{http_code} time=%{time_total}s\n' \
    "$BASE/internal-api/build-mempool-summary?statusId=$ID"
cat /tmp/build.json; echo

sleep 1

echo "=== mempool-summary-status ==="
curl -s -w '\nHTTP=%{http_code}\n' \
    "$BASE/internal-api/mempool-summary-status?statusId=$ID"

echo "=== get-mempool-summary (top-level fields only) ==="
curl -s "$BASE/internal-api/get-mempool-summary?statusId=$ID" > /tmp/sum.json || true
wc -c /tmp/sum.json
python3 - <<'PY' || true
import json
with open("/tmp/sum.json") as f:
    d = json.load(f)
print({k: (f"<list len={len(v)}>" if isinstance(v, list) else v) for k, v in d.items()})
PY
