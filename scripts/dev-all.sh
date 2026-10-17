#!/usr/bin/env bash
# Start the whole VaidyaVaani dev stack: LiveKit, the HTTPS tunnel, the Clinic
# Console and Next.js. Ports come from .env.example (docs/04 §1).
#
# Start order is deliberate: the tunnel comes up BEFORE the console, because the
# take-home QR encodes CONSOLE_PUBLIC_URL and a QR pointing at 127.0.0.1 is
# useless on a patient's phone. We bring the tunnel up first, read its hostname,
# and hand it to the console as CONSOLE_PUBLIC_URL.
#
# That order used to be only a convention with a silent fallback behind it: no
# tunnel meant CONSOLE_PUBLIC_URL quietly became a loopback address, and nothing
# revealed the dead QR until a judge's phone scanned it. It is now a guard —
# scripts/preflight.sh --qr-url refuses to let the console start on a URL no
# phone can reach. Pass --no-qr to start anyway and accept a dead QR, out loud.
#
# Verified commands (console/README.md, web/package.json):
#   console : console/.venv/bin/python -m app.main --port 8808   (health: /healthz)
#   web     : npm run dev                     (port 3000 is baked into the script)
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
# shellcheck source=/dev/null
source "$REPO_ROOT/scripts/lib-env.sh"

MOCK=""; NO_QR=""; SKIP_PREFLIGHT=""
for a in "$@"; do
  case "$a" in
    --mock) MOCK="--mock" ;;
    # Start without a reachable take-home QR. You must ask for this; you cannot get it by
    # accident, which was the whole problem.
    --no-qr) NO_QR="1" ;;
    --skip-preflight) SKIP_PREFLIGHT="1" ;;
    *) echo "dev-all: unknown argument '$a' (--mock | --no-qr | --skip-preflight)" >&2; exit 2 ;;
  esac
done

LOG_DIR="$REPO_ROOT/.dev-logs"; mkdir -p "$LOG_DIR"
PIDS=()

cleanup() {
  echo ""; echo "Shutting down..."
  for pid in "${PIDS[@]:-}"; do [ -n "${pid:-}" ] && kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  echo "Stopped. Logs kept in $LOG_DIR/"
}
trap cleanup EXIT INT TERM

start() { local name="$1"; shift
  echo "  starting $name  (log: $LOG_DIR/$name.log)"
  "$@" > "$LOG_DIR/$name.log" 2>&1 &
  PIDS+=("$!")
}
wait_for() { local i=0
  until curl -s -o /dev/null --max-time 2 "$1"; do
    i=$((i+1))
    [ "$i" -ge "${3:-30}" ] && { echo "  ✗ $2 not up at $1 — see $LOG_DIR/$2.log" >&2; return 1; }
    sleep 1
  done
  echo "  ✓ $2 up at $1"
}

# ---- 0. Preflight, before anything matters --------------------------------
# --stack: a missing OPENAI_API_KEY or UNMUTE_DEV_METRICS is reported loudly but does not stop
# the stack coming up — the console and UI are still worth having without an LLM key. Anything
# that would make the stack itself wrong (no cloudflared, a console off 127.0.0.1, a cached
# tunnel hostname) is fatal here. Run scripts/preflight.sh with no arguments for the full gate.
if [ -z "$SKIP_PREFLIGHT" ]; then
  if ! "$REPO_ROOT/scripts/preflight.sh" --stack; then
    echo "" >&2
    echo "Preflight failed. Fix the ✗ lines above, or re-run with --skip-preflight if you" >&2
    echo "know exactly why you are overriding it." >&2
    exit 1
  fi
  echo ""
fi

echo "VaidyaVaani dev stack${MOCK:+  (console in MOCK mode)}"
echo "  console  http://127.0.0.1:$CONSOLE_PORT"
echo "  web      http://127.0.0.1:$WEB_PORT"
echo "  livekit  ws://127.0.0.1:$LIVEKIT_PORT"
echo ""

# ---- 1. LiveKit -----------------------------------------------------------
if lsof -nP -iTCP:"$LIVEKIT_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "  ✓ livekit already running on $LIVEKIT_PORT"
else
  command -v livekit-server >/dev/null 2>&1 \
    && { start livekit livekit-server --dev; wait_for "http://127.0.0.1:$LIVEKIT_PORT/" livekit 20 || true; } \
    || echo "  ! livekit-server not installed (brew install livekit)" >&2
fi

# ---- 2. HTTPS tunnel, FIRST, so the QR can point at it --------------------
PUBLIC_URL=""
if command -v cloudflared >/dev/null 2>&1; then
  start tunnel cloudflared tunnel --url "http://127.0.0.1:$WEB_PORT" --no-autoupdate
  echo -n "  waiting for the tunnel hostname"
  for _ in $(seq 1 40); do
    PUBLIC_URL="$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG_DIR/tunnel.log" 2>/dev/null | head -1)"
    [ -n "$PUBLIC_URL" ] && break
    echo -n "."; sleep 1
  done; echo ""
  [ -n "$PUBLIC_URL" ] && echo "  ✓ tunnel $PUBLIC_URL" \
                       || echo "  ! no tunnel hostname — see $LOG_DIR/tunnel.log" >&2
else
  echo "  ! cloudflared not installed (brew install cloudflared) — no phone URL" >&2
fi

# ---- 2b. THE ORDERING GUARD ------------------------------------------------
# The console is about to be handed CONSOLE_PUBLIC_URL, and that value is what the take-home QR
# encodes. If the tunnel did not come up, the old code fell back to a loopback address and
# carried on — a QR no phone can reach, discovered on stage. Now the run dies here instead.
echo ""
if [ -n "$NO_QR" ]; then
  echo "  ! --no-qr: starting without a reachable take-home QR. The QR in the UI will point at" >&2
  echo "    a loopback address and NO PHONE CAN SCAN IT. Do not demo the take-home step." >&2
  PUBLIC_URL=""
elif ! "$REPO_ROOT/scripts/preflight.sh" --qr-url "$PUBLIC_URL"; then
  exit 1
fi

# ---- 3. Clinic Console ----------------------------------------------------
# CONSOLE_PUBLIC_URL is what the take-home QR encodes; point it at the tunnel so
# the patient's phone can actually reach the voice note.
if [ -f "$REPO_ROOT/console/app/main.py" ]; then
  if [ ! -x "$REPO_ROOT/console/.venv/bin/python" ]; then
    echo "  console venv missing — creating it (console/README.md)"
    (cd "$REPO_ROOT/console" && python3 -m venv .venv \
      && .venv/bin/pip install -q -r requirements-dev.txt) \
      || echo "  ! console venv setup failed" >&2
  fi
  if [ -x "$REPO_ROOT/console/.venv/bin/python" ]; then
    start console env -C "$REPO_ROOT/console" \
      CONSOLE_PUBLIC_URL="${PUBLIC_URL:-http://127.0.0.1:$WEB_PORT}" \
      .venv/bin/python -m app.main --port "$CONSOLE_PORT" ${MOCK:+$MOCK}
    wait_for "http://127.0.0.1:$CONSOLE_PORT/healthz" console 40 || true
  fi
else
  echo "  – console/ not present, skipping"
fi

# ---- 4. Next.js -----------------------------------------------------------
# Port 3000 is baked into web/package.json's `next dev -p 3000`; don't pass it.
if [ -f "$REPO_ROOT/web/package.json" ]; then
  [ -d "$REPO_ROOT/web/node_modules" ] || { echo "  installing web deps..."; (cd "$REPO_ROOT/web" && npm install --silent); }
  start web env -C "$REPO_ROOT/web" npm run dev
  wait_for "http://127.0.0.1:$WEB_PORT/" web 90 || true
else
  echo "  – web/ not present, skipping"
fi

if [ -n "$PUBLIC_URL" ]; then
  echo ""
  echo "  ========================================================"
  echo "  PHONE URL (the mic needs this HTTPS origin, not the IP):"
  echo "  $PUBLIC_URL"
  echo "  ========================================================"
  echo "  A quick tunnel gets a NEW RANDOM HOSTNAME on every restart."
  echo "  Nothing caches it and nothing may: generate the demo QR from"
  echo "  this running stack, AFTER this line. Never pre-generate it,"
  echo "  never put this URL on a slide, never paste it into .env."
  echo "  Restart the stack and every one of those is silently wrong."
fi
echo ""
echo "Running. Ctrl-C to stop everything."
wait
