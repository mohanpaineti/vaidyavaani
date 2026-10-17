"""Runtime configuration. Everything is env-overridable; every default is localhost-safe."""

from __future__ import annotations

import os
from pathlib import Path

CONSOLE_VERSION = "0.1.0"

# console/
CONSOLE_DIR = Path(__file__).resolve().parent.parent
# repo root
REPO_ROOT = CONSOLE_DIR.parent

HOST = "127.0.0.1"          # never 0.0.0.0 — the tunnel fronts Next.js, not the console
PORT = int(os.environ.get("CONSOLE_PORT", "8808"))

# Shared secret checked on every /api/tools/* call (docs/04 §3).
CONSOLE_TOKEN = os.environ.get("CONSOLE_TOKEN", "dev-console-token")
CONSOLE_TOKEN_IS_DEFAULT = "CONSOLE_TOKEN" not in os.environ

# Public base URL used inside the take-home QR code (the Cloudflare tunnel, in the demo).
PUBLIC_URL = os.environ.get("CONSOLE_PUBLIC_URL", f"http://{HOST}:{PORT}")

# LiveKit (token mint only — the console is never in the media path).
LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "ws://127.0.0.1:7880")
LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "devkey")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "secret")
LIVEKIT_IS_CONFIGURED = bool(
    os.environ.get("LIVEKIT_API_KEY") and os.environ.get("LIVEKIT_API_SECRET")
)
LIVEKIT_TOKEN_TTL_SECONDS = int(os.environ.get("LIVEKIT_TOKEN_TTL_SECONDS", "3600"))

# The name the generated worker registers under. It originates in the compiled package —
# `vaidyavaani-agent/build/livekit/agent.py`: `@server.rtc_session(agent_name="vaidyavaani-livekit")`
# — which `unmute compile` derives from the package name and the target. A worker that declares an
# agent name is **excluded from LiveKit's automatic dispatch** and joins only when something asks
# for it by name, so the console has to say the name when it mints a join token (see tokens.py).
# Env-overridable precisely so the two places cannot drift silently if the package is renamed.
LIVEKIT_AGENT_NAME = os.environ.get("LIVEKIT_AGENT_NAME", "vaidyavaani-livekit")

# Content, owned by content-eval. There is deliberately no fallback copy inside console/: a
# second copy of someone else's content can only drift, and a stale one once manufactured a
# failure that cost two sessions a round trip. If these files are missing the console says so at
# startup instead of rendering from a snapshot.
CONTENT_DIR = Path(
    os.environ.get("CONSOLE_CONTENT_DIR", str(REPO_ROOT / "content"))
).expanduser()

# unmute writes measurements here.
DEV_LOG_PATH = Path(
    os.environ.get("CONSOLE_DEV_LOG", str(REPO_ROOT / "build" / "livekit" / "dev.log"))
).expanduser()
FIXTURE_DEV_LOG = CONSOLE_DIR / "tests" / "fixtures" / "dev.log.sample"

# The only thing that outlives a session.
DEMAND_LOG_PATH = Path(
    os.environ.get("CONSOLE_DEMAND_LOG", str(CONSOLE_DIR / "demand_log.jsonl"))
).expanduser()

# The gate.
CONFIRMATION_LONGPOLL_SECONDS = float(os.environ.get("CONSOLE_LONGPOLL_SECONDS", "25"))

# Privacy posture.
VOICE_NOTE_TTL_SECONDS = int(os.environ.get("CONSOLE_VOICE_NOTE_TTL", str(30 * 60)))
SWEEP_INTERVAL_SECONDS = float(os.environ.get("CONSOLE_SWEEP_INTERVAL", "60"))
SESSION_IDLE_SECONDS = float(os.environ.get("CONSOLE_SESSION_IDLE_SECONDS", "600"))
# Grace after the last browser WS drops, so a reload does not destroy a live consultation.
DISCONNECT_GRACE_SECONDS = float(os.environ.get("CONSOLE_DISCONNECT_GRACE", "30"))

# Mock mode (docs/04 §7). Set by --mock or CONSOLE_MOCK=1.
MOCK = os.environ.get("CONSOLE_MOCK", "") not in ("", "0", "false", "False")
MOCK_SCRIPT_PATH = Path(
    os.environ.get(
        "CONSOLE_MOCK_SCRIPT", str(CONSOLE_DIR / "tests" / "fixtures" / "consultation.json")
    )
).expanduser()
# Mock only: tap confirm-all by itself after this many seconds, for an unattended replay.
# 0 (the default) means the replay waits at the gate for a real tap, exactly like the real thing.
MOCK_AUTO_CONFIRM_SECONDS = float(os.environ.get("CONSOLE_MOCK_AUTO_CONFIRM", "0"))
