#!/usr/bin/env bash
# Deploy to Fly. Run AFTER `fly auth login`.
#
# Fly builds the image on a remote builder, so Docker is not needed locally.
set -euo pipefail
cd "$(dirname "$0")/.."

flyctl auth whoami >/dev/null 2>&1 || {
  echo "Not authenticated. Run:  fly auth login"; exit 1; }

APP=$(awk -F'"' '/^app =/{print $2}' fly.toml)
echo "deploying $APP as $(flyctl auth whoami)"

flyctl apps list 2>/dev/null | grep -q "^$APP" \
  || flyctl apps create "$APP" --machines

# --ha=false keeps it to a single machine: in-memory state must not be split.
flyctl deploy --ha=false --wait-timeout 300

URL="https://$APP.fly.dev"
echo "deployed: $URL"
flyctl status
echo
./scripts/preflight.sh "$URL"
