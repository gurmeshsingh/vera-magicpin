#!/usr/bin/env bash
# Pre-submission checklist, run against a live URL.
#   ./scripts/preflight.sh https://your-host.example.com
set -uo pipefail
BASE="${1:?usage: preflight.sh <base-url>}"
pass=0; fail=0
chk() { if [ "$2" = "$3" ]; then echo "  PASS  $1"; pass=$((pass+1)); else echo "  FAIL  $1 (got $2, want $3)"; fail=$((fail+1)); fi; }

echo "preflight against $BASE"
chk "healthz 200"  "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/v1/healthz")" "200"
chk "metadata 200" "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/v1/metadata")" "200"
chk "tick 200"     "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/v1/tick" -H 'Content-Type: application/json' -d '{"now":"2026-04-26T10:00:00Z","available_triggers":[]}')" "200"
chk "reply 200"    "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/v1/reply" -H 'Content-Type: application/json' -d '{"conversation_id":"c1","merchant_id":"m1","from_role":"merchant","message":"hi","turn_number":1}')" "200"
chk "context 200"  "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/v1/context" -H 'Content-Type: application/json' -d '{"scope":"category","context_id":"dentists","version":1,"payload":{"slug":"dentists"}}')" "200"
chk "garbage push still 200" "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/v1/context" -H 'Content-Type: application/json' -d '{"nonsense":true}')" "200"
chk "equal-version re-push accepts" "$(curl -s -X POST "$BASE/v1/context" -H 'Content-Type: application/json' -d '{"scope":"category","context_id":"dentists","version":1,"payload":{"slug":"dentists"}}' | grep -c '"accepted":true')" "1"

lat=$(curl -s -o /dev/null -w '%{time_total}' "$BASE/v1/healthz")
echo "  healthz latency ${lat}s (judge cuts off at 5s)"
awk -v l="$lat" 'BEGIN{exit !(l<1.0)}' && echo "  PASS  healthz comfortably inside budget" && pass=$((pass+1)) || { echo "  FAIL  healthz too slow"; fail=$((fail+1)); }

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ] || exit 1
