#!/usr/bin/env bash
# Start the local LiveKit dev server for VaidyaVaani.
#
# Verified in P0 (docs/03-p0-findings.md): --dev mode binds 127.0.0.1:7880 and
# uses the placeholder credentials devkey/secret, which is exactly what
# .env.example and docs/04 §1 declare. A token minted with devkey/secret is
# accepted by /rtc/validate (HTTP 200 "success").
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
[ -f "$REPO_ROOT/scripts/lib-env.sh" ] && source "$REPO_ROOT/scripts/lib-env.sh"

if ! command -v livekit-server >/dev/null 2>&1; then
  echo "livekit-server not found. Install it with:" >&2
  echo "  brew install livekit" >&2
  exit 1
fi

PORT="${LIVEKIT_PORT:-7880}"
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is already in use — LiveKit may already be running." >&2
  echo "Check with: lsof -nP -iTCP:$PORT -sTCP:LISTEN" >&2
  exit 1
fi

echo "LiveKit dev server  ws://127.0.0.1:$PORT   (key: devkey / secret: secret)"
echo "These are DEV-ONLY placeholder credentials. Never use them off localhost."
exec livekit-server --dev
