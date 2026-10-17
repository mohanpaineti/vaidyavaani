#!/usr/bin/env bash
# HTTPS tunnel in front of the Next.js dev server (port 3000).
#
# Why this exists: a phone browser refuses getUserMedia outside a secure
# context, so the mic is dead over plain http://<laptop-ip>:3000. A Cloudflare
# quick tunnel gives us a real HTTPS origin, which makes window.isSecureContext
# true and the mic available. Verified in P0 — see docs/03-p0-findings.md.
#
# The tunnel fronts Next.js ONLY. The console stays bound to 127.0.0.1
# (docs/04 §1) and is never exposed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
[ -f "$REPO_ROOT/scripts/lib-env.sh" ] && source "$REPO_ROOT/scripts/lib-env.sh"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared not found. Install it with:" >&2
  echo "  brew install cloudflared" >&2
  exit 1
fi

PORT="${WEB_PORT:-3000}"
if ! curl -s -o /dev/null --max-time 3 "http://127.0.0.1:$PORT/"; then
  echo "Nothing is serving http://127.0.0.1:$PORT yet." >&2
  echo "Start the web app first (scripts/dev-all.sh does both)." >&2
  exit 1
fi

echo "Opening an HTTPS tunnel to http://127.0.0.1:$PORT ..."
echo "Open the https://<name>.trycloudflare.com URL below ON THE PHONE."
echo "A quick tunnel gets a NEW random hostname every restart — re-scan after a restart."
exec cloudflared tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate
