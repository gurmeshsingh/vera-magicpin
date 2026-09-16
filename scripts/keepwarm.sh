#!/usr/bin/env bash
# Keep the Render free instance from idling out.
#
# This does NOT fix the ~13% health-check failure rate measured on the free
# tier -- that is resource contention and only a paid plan removes it. What it
# does fix is the other failure mode: a free service spins down after ~15
# minutes idle and then cold-starts in 50+ seconds. If the judge's first
# healthz poll lands on a cold start, that is one failure before the run even
# begins.
#
# Run it in a terminal from a few hours before your slot until the run ends:
#   ./scripts/keepwarm.sh
set -uo pipefail
URL="${1:-https://vera-magicpin-gs.onrender.com}"
INTERVAL="${2:-600}"   # 10 min; free tier idles at ~15

echo "keeping $URL warm every ${INTERVAL}s — ctrl-c to stop"
while true; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$URL/v1/healthz" 2>/dev/null || echo "000")
  printf '%s  healthz %s\n' "$(date '+%H:%M:%S')" "$code"
  sleep "$INTERVAL"
done
