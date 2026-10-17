#!/usr/bin/env bash
# Preflight — every precondition the demo needs, checked loudly, before it matters.
#
# Why this exists: all three of the worst failures this project has found so far are SILENT.
# A dead take-home QR looks fine until a judge's phone scans it. An unset UNMUTE_DEV_METRICS
# leaves the metrics HUD empty with nothing to explain why. A missing OPENAI_API_KEY surfaces
# as the agent simply never answering. None of them throws anything you would notice on stage.
# So they get checked here, by name, with the fix in the message.
#
# Never prints a secret value. Presence only — scripts/lib-env.sh already warns that .env may
# hold the SLNG key.
#
# Usage:
#   scripts/preflight.sh              full gate. Run this before you walk on stage. Exit 1 on any FAIL.
#   scripts/preflight.sh --stack      only what dev-all.sh needs in order to START the stack.
#                                     Live-turn preconditions are still reported, loudly, but do
#                                     not block the stack from coming up. dev-all.sh uses this.
#   scripts/preflight.sh --qr-url URL the ordering guard. Exit 1 unless URL is a public HTTPS
#                                     origin a patient's phone can actually reach.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$REPO_ROOT/scripts/lib-env.sh"

MODE="full"
QR_URL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --stack)   MODE="stack" ;;
    --qr-url)  MODE="qr"; QR_URL="${2:-}"; shift ;;
    --qr-url=*) MODE="qr"; QR_URL="${1#*=}" ;;
    -h|--help) sed -n '2,22p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "preflight: unknown argument '$1'" >&2; exit 2 ;;
  esac
  shift
done

FAILS=0      # blocks
DEFERS=0     # would block a live turn, but not the stack coming up

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
note() { printf '    %s\n' "$1"; }
fail() { printf '  \033[31m✗ %s\033[0m\n' "$1"; printf '    → %s\n' "$2"; FAILS=$((FAILS+1)); }
# A precondition for the first live turn. Fatal in full mode; reported but survivable in --stack,
# because a stack that comes up with no LLM key is still worth having for UI and console work.
live() {
  if [ "$MODE" = "stack" ]; then
    printf '  \033[33m✗ %s\033[0m\n' "$1"; printf '    → %s\n' "$2"
    printf '    (blocks the first live turn — not this stack starting)\n'
    DEFERS=$((DEFERS+1))
  else
    fail "$1" "$2"
  fi
}

# ── Is this URL something a phone on mobile data can reach? ─────────────────────────────────
# Used both by the --qr-url ordering guard and by the CONSOLE_PUBLIC_URL check.
url_is_reachable_from_a_phone() {
  local u="${1:-}" host
  [ -n "$u" ] || return 1
  case "$u" in https://*) ;; *) return 1 ;; esac
  host="${u#https://}"; host="${host%%/*}"; host="${host%%:*}"
  case "$host" in
    127.*|localhost|::1|\[::1\]|0.0.0.0|10.*|192.168.*|*.local) return 1 ;;
    172.1[6-9].*|172.2[0-9].*|172.3[0-1].*) return 1 ;;
  esac
  return 0
}

# ── The ordering guard ──────────────────────────────────────────────────────────────────────
# The take-home QR encodes CONSOLE_PUBLIC_URL (console/app/config.py:23), which falls back to
# 127.0.0.1 when the tunnel is not up. That is a QR no phone can reach and NOTHING reveals it
# until somebody scans it in front of judges. So: the tunnel starts before the console, and if
# the URL still looks like a loopback address when the console is about to come up, the run dies
# here rather than proceeding with a dead QR.
if [ "$MODE" = "qr" ]; then
  echo "Preflight — take-home QR origin"
  if [ -z "$QR_URL" ]; then
    fail "no tunnel hostname — CONSOLE_PUBLIC_URL would fall back to a loopback address" \
         "the tunnel did not come up. Check .dev-logs/tunnel.log, then re-run scripts/dev-all.sh. To start the stack anyway and accept that the take-home QR is dead for this run, pass --no-qr."
  elif ! url_is_reachable_from_a_phone "$QR_URL"; then
    fail "CONSOLE_PUBLIC_URL is '$QR_URL' — a patient's phone cannot reach that" \
         "the QR must encode the public HTTPS tunnel origin. Start the stack with scripts/dev-all.sh, which brings the tunnel up BEFORE the console, and never start the console by hand."
  else
    ok "QR origin is a public HTTPS host the phone can reach"
    note "$QR_URL"
    note "This hostname is NEW on every tunnel restart. Nothing caches it, and nothing may:"
    note "generate the QR from this running stack — never pre-generate it, never put it on a slide."
  fi
  [ "$FAILS" -eq 0 ] && exit 0
  echo ""
  printf '\033[31mRefusing to start the console with a dead take-home QR.\033[0m\n'
  exit 1
fi

echo "VaidyaVaani preflight${MODE:+  ($MODE)}"
echo ""

# ── 1. Binaries ─────────────────────────────────────────────────────────────────────────────
echo "Toolchain"
for tool in voiceai cloudflared livekit-server node npm python3; do
  if command -v "$tool" >/dev/null 2>&1; then
    ok "$tool"
  else
    case "$tool" in
      voiceai)        fail "voiceai not found" "pip install voiceai-sdk (or see docs/03 §1)" ;;
      cloudflared)    fail "cloudflared not found" "brew install cloudflared — without it there is no HTTPS origin, so no phone mic and no reachable QR" ;;
      livekit-server) fail "livekit-server not found" "brew install livekit" ;;
      node|npm)       fail "$tool not found" "brew install node" ;;
      python3)        fail "python3 not found" "console/README.md pins python 3.14" ;;
    esac
  fi
done
echo ""

# ── 2. The SLNG speech credential ───────────────────────────────────────────────────────────
echo "Credentials"
if command -v voiceai >/dev/null 2>&1; then
  WHOAMI="$(voiceai whoami 2>&1)"; WHOAMI_RC=$?
  # voiceai exits 0 even when it reports "no API key set", so match the output, not the status.
  if [ "$WHOAMI_RC" -ne 0 ] || [ -z "$WHOAMI" ] || printf '%s' "$WHOAMI" | grep -qi '^error:\|no API key'; then
    fail "voiceai whoami reports no usable credential" \
         "run 'voiceai login' — the generated worker reads SLNG_API_KEY for STT and TTS. If it works in a plain shell but not here, something is exporting an EMPTY VOICEAI_API_KEY or SLNG_API_KEY over it; an empty value shadows ~/.config/voiceai/config.json."
  elif printf '%s' "$WHOAMI" | grep -q 'region: *in'; then
    ok "voiceai whoami — region: in"
  else
    fail "voiceai whoami does not report region: in" "re-run 'voiceai login' and pick the India region. Saaras and Bulbul are the India-hosted models (docs/03 §4); the wrong region silently moves patient audio out of the country."
  fi
fi

# OPENAI_API_KEY — presence only, never the value. This is THE thing blocking the first live
# turn today (docs/00 §4.1). `unmute compile` puts it in required_env; the generated worker
# builds openai.LLM() with it, so without it the agent cannot think and simply never answers.
if [ -n "${OPENAI_API_KEY:-}" ]; then
  ok "OPENAI_API_KEY present (${#OPENAI_API_KEY} chars — value never printed)"
else
  live "OPENAI_API_KEY is not set — the agent cannot think, so no live turn can run" \
       "put a plain OpenAI key in .env as OPENAI_API_KEY=... (quick route, docs/00 §4.1). The better route is an SLNG Execution Layer project key via BYOK — same §4.1, four dashboard steps. .env is gitignored; never commit it."
fi

# UNMUTE_DEV_METRICS — unset means unmute emits NO dev.log records at all. metrics_enabled()
# returns false unless it is set to something other than "" or "0" (docs/03 §14). The HUD is
# then silently empty, and the parser everyone will blame is innocent.
case "${UNMUTE_DEV_METRICS:-}" in
  ""|0)
    live "UNMUTE_DEV_METRICS is unset or 0 — unmute emits NO dev.log records at all" \
         "set UNMUTE_DEV_METRICS=1 in .env, and export it in the shell that starts the generated worker. With it unset the metrics HUD is empty with nothing to explain why, and no latency number can ever be measured (docs/03 §14)." ;;
  *) ok "UNMUTE_DEV_METRICS=${UNMUTE_DEV_METRICS} — dev.log records will be emitted" ;;
esac
echo ""

# ── 3. The env contract, docs/04 §1 ─────────────────────────────────────────────────────────
echo "Env contract (docs/04 §1)"
require() { # $1 name, $2 fix
  if [ -n "${!1:-}" ]; then ok "$1 set"; else fail "$1 is not set" "$2"; fi
}
require CONSOLE_TOKEN      "the shared secret on X-Console-Token for every agent tool call. Set it in .env; the console falls back to a default and warns."
require CONSOLE_URL        "http://127.0.0.1:8808 — see .env.example"
require NEXT_PUBLIC_CONSOLE_URL "http://127.0.0.1:8808 — the browser reads this at build time; Next.js inlines NEXT_PUBLIC_* so a change needs a restart."
require LIVEKIT_URL        "ws://127.0.0.1:7880 — see .env.example"
require LIVEKIT_API_KEY    "devkey for the local dev server — see .env.example"
require LIVEKIT_API_SECRET "secret for the local dev server — see .env.example"

if [ "${CONSOLE_TOKEN:-}" = "change-me-local-dev-only" ]; then
  note "CONSOLE_TOKEN is still the .env.example placeholder. Fine on localhost; it is only a"
  note "shared secret between the console and the agent's tool handlers, both on this machine."
fi

# CONSOLE_PUBLIC_URL must NOT be a stored value. A Cloudflare quick tunnel takes a new random
# hostname on EVERY restart, so any hostname written into .env is already wrong.
if grep -qsE '^[[:space:]]*CONSOLE_PUBLIC_URL[[:space:]]*=[[:space:]]*[^[:space:]]' \
     "$REPO_ROOT/.env" "$REPO_ROOT/.env.example" 2>/dev/null; then
  fail "CONSOLE_PUBLIC_URL has a stored value in .env or .env.example" \
       "delete that line. A Cloudflare quick tunnel gets a NEW random hostname every restart, so a stored one points at a tunnel that no longer exists — a dead QR that looks healthy. dev-all.sh reads the live hostname and passes it to the console for that run only."
else
  ok "CONSOLE_PUBLIC_URL is not cached anywhere — set per run from the live tunnel"
fi
echo ""

# ── 4. The console must never leave 127.0.0.1 ───────────────────────────────────────────────
# The tunnel fronts Next.js, not the console (docs/04 §1). A console on 0.0.0.0 behind a public
# tunnel would put the gate, the transcript and the voice notes on the open internet.
echo "Binding"
CFG="$REPO_ROOT/console/app/config.py"
if [ -f "$CFG" ]; then
  HOST_LINE="$(grep -E '^HOST[[:space:]]*=' "$CFG" | head -1)"
  case "$HOST_LINE" in
    *'"127.0.0.1"'*|*"'127.0.0.1'"*) ok "console binds 127.0.0.1 (console/app/config.py)" ;;
    "") fail "no HOST = line in console/app/config.py" "the console's bind address could not be verified — read console/app/config.py before running this in front of anyone." ;;
    *)  fail "console/app/config.py HOST is not 127.0.0.1: ${HOST_LINE}" \
             "set HOST = \"127.0.0.1\". The tunnel fronts Next.js, not the console (docs/04 §1); a console on 0.0.0.0 behind a public tunnel exposes the gate, the transcript and the voice notes." ;;
  esac
  # Comments stripped first: config.py's HOST line carries the words "never 0.0.0.0".
  if sed 's/#.*//' "$CFG" | grep -qE '0\.0\.0\.0'; then
    fail "0.0.0.0 appears in console/app/config.py" "remove it — the console is never reachable off this machine (docs/04 §1)."
  fi
fi
for n in CONSOLE_URL NEXT_PUBLIC_CONSOLE_URL; do
  v="${!n:-}"
  case "$v" in
    ""|http://127.0.0.1:*|http://localhost:*) ;;
    *) fail "$n is '$v' — not a loopback address" "the console is only ever reached over 127.0.0.1 (docs/04 §1)." ;;
  esac
done
echo ""

# ── 5. Ports ────────────────────────────────────────────────────────────────────────────────
# A stale console on 8808 is FATAL, and this is not fussiness. dev-all.sh's health check is a
# GET on /healthz, which a leftover console answers just as happily as a new one: the new console
# fails to bind, the script prints "✓ console up", and the stack silently keeps running the OLD
# console — carrying the OLD CONSOLE_PUBLIC_URL. Observed here on 2026-10-17: an aborted --no-qr
# run left a console holding 8808 with a loopback public URL, a clean run with a live tunnel
# reported every service green, and the QR was still dead. The ordering guard cannot see this,
# because by then the console it is guarding is not the console that is running.
echo "Ports"
if lsof -nP -iTCP:"$CONSOLE_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  fail "port $CONSOLE_PORT already has a listener — a console from an earlier run" \
       "stop it first: lsof -nP -iTCP:$CONSOLE_PORT -sTCP:LISTEN -t | xargs kill. A leftover console answers /healthz, so dev-all.sh would report '✓ console up' while the new console failed to bind — and the stack would keep the OLD CONSOLE_PUBLIC_URL, i.e. the dead QR the guard exists to prevent."
else
  ok "port $CONSOLE_PORT (console) free"
fi
# Next.js on a stale port serves stale code behind a fresh tunnel. Loud, but not fatal.
if lsof -nP -iTCP:"$WEB_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  printf '  \033[33m! port %s (web) already has a listener\033[0m\n' "$WEB_PORT"
  note "the new tunnel will front whatever that is — stale code, possibly. Stop it if in doubt."
else
  ok "port $WEB_PORT (web) free"
fi
# LiveKit is stateless here and dev-all.sh deliberately reuses one that is already up.
if lsof -nP -iTCP:"$LIVEKIT_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  note "port $LIVEKIT_PORT (livekit) already has a listener — dev-all.sh reuses it, which is fine"
else
  ok "port $LIVEKIT_PORT (livekit) free"
fi
echo ""

# ── Verdict ─────────────────────────────────────────────────────────────────────────────────
if [ "$FAILS" -gt 0 ]; then
  printf '\033[31m%s precondition(s) failed.\033[0m Fix the ✗ lines above, then re-run.\n' "$FAILS"
  exit 1
fi
if [ "$DEFERS" -gt 0 ]; then
  printf '\033[33m%s live-turn precondition(s) missing.\033[0m The stack will start; the agent will not\n' "$DEFERS"
  printf 'answer and the metrics HUD may stay empty. Fix the ✗ lines before claiming any number.\n'
  exit 0
fi
printf '\033[32mAll preconditions met.\033[0m\n'
exit 0
