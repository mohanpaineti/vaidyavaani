"""Mock mode — docs/04 §7.

`--mock` replays a canned consultation over the WebSocket so `web-console` can build without the
agent. The replay drives the *same* server code paths as the agent's tool calls, so every frame the
browser sees is produced by the real implementation: the mock/real difference stays entirely inside
the server and `web/lib/console-ws.ts` needs no `if (mock)` branch.

The script format is ours (`tests/fixtures/consultation.json`); its clinical content is
content-eval's. One step per entry:

    {"after_ms": 400, "op": "<op>", ...}

ops: `stage`, `partial`, `turn`, `consent`, `lang_detected`, `red_flag`, `rx_draft`,
`await_confirm`, `teachback`, `voice_note`, `metric`, `failover`, `error`, `end`.

`await_confirm` blocks until the doctor taps confirm-all in the browser — the gate is real in mock
mode too. Set `CONSOLE_MOCK_AUTO_CONFIRM=<seconds>` for an unattended replay.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from . import config, confirmation, teachback, voicenotes
from .models import RedFlag, RxLine, Turn, VoiceNote, now_iso
from .sessions import Session, SessionStore

log = logging.getLogger("console.mock")


class MockScriptError(RuntimeError):
    pass


def load_script(path: Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else config.MOCK_SCRIPT_PATH
    if not target.exists():
        raise MockScriptError(f"mock script not found: {target}")
    try:
        script = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MockScriptError(f"{target} is not valid JSON: {exc}") from exc
    if not isinstance(script, dict) or not isinstance(script.get("steps"), list):
        raise MockScriptError(f"{target} must be an object with a 'steps' list")
    return script


async def _auto_confirm(session: Session, store: SessionStore, delay: float) -> None:
    await asyncio.sleep(delay)
    for line in session.state.prescription.lines:
        line.confirmed = True
        await store.line_updated(session, line)
    try:
        await confirmation.confirm_all(session, store)
    except Exception:
        log.exception("mock auto-confirm failed")


async def replay(
    session: Session, store: SessionStore, script: dict[str, Any] | None = None
) -> None:
    """Run the canned consultation against a live session. Cancellable."""
    script = script or load_script()
    session_id = session.state.session_id
    if script.get("patient_language"):
        session.state.patient_language = script["patient_language"]
        await store.broadcast(
            session_id,
            {
                "type": "lang_detected",
                "lang": script["patient_language"],
                "confidence": script.get("language_confidence"),
            },
        )

    for step in script["steps"]:
        await asyncio.sleep(max(0.0, float(step.get("after_ms", 0))) / 1000.0)
        if session_id not in store.ids():
            log.info("mock replay stopped: session %s is gone", session_id)
            return
        op = step.get("op")
        try:
            await _apply(op, step, session, store)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("mock step %r failed", op)


async def _apply(op: str, step: dict[str, Any], session: Session, store: SessionStore) -> None:
    session_id = session.state.session_id

    if op == "stage":
        await store.set_stage(session, step["stage"])

    elif op == "partial":
        await store.broadcast(
            session_id,
            {"type": "partial", "side": step.get("side", "patient"), "text": step.get("text", "")},
        )

    elif op == "turn":
        await store.add_turn(session, Turn(**step["turn"]))

    elif op == "consent":
        session.state.consent.given = bool(step.get("given", True))
        session.state.consent.at = now_iso()
        await store.broadcast(
            session_id, {"type": "state_snapshot", "state": session.state.model_dump()}
        )

    elif op == "lang_detected":
        session.state.patient_language = step["lang"]
        await store.broadcast(
            session_id,
            {"type": "lang_detected", "lang": step["lang"], "confidence": step.get("confidence")},
        )

    elif op == "red_flag":
        await store.add_red_flag(session, RedFlag(**step["red_flag"]))

    elif op == "rx_draft":
        lines = [RxLine(**raw) for raw in step["lines"]]
        await store.publish_draft(session, lines, step.get("ambiguities", []))
        confirmation.reopen(session)
        await store.set_stage(session, "await_confirm")

    elif op == "await_confirm":
        if config.MOCK_AUTO_CONFIRM_SECONDS > 0:
            asyncio.create_task(
                _auto_confirm(session, store, config.MOCK_AUTO_CONFIRM_SECONDS)
            )
        log.info("mock replay waiting at the gate for session %s", session_id)
        while session.gate_outcome != confirmation.STATUS_CONFIRMED:
            answer = await confirmation.await_confirmation(session, timeout=3600)
            if answer["status"] == confirmation.STATUS_REJECTED:
                # The doctor rejected the draft. Wait for the next thing they do rather than
                # spinning on a rejection that poll_now will keep returning.
                session.gate_event.clear()
                await session.gate_event.wait()

    elif op == "teachback":
        result = teachback.compare(
            session.state.prescription.lines,
            patient_text=step.get("patient_text", ""),
            english_text=step.get("english_text", ""),
            patient_said=step.get("patient_said"),
        )
        session.state.teachback = result
        await store.set_stage(session, "teachback")
        await store.broadcast(
            session_id, {"type": "teachback_result", "result": result.model_dump()}
        )

    elif op == "voice_note":
        record = voicenotes.store.create(
            session_id=session_id,
            text=step.get("text", ""),
            language=step.get("language", session.state.patient_language or "ta"),
        )
        url = voicenotes.public_url(record.token)
        data_uri = voicenotes.qr_data_uri(url)
        session.state.voice_note = VoiceNote(
            token=record.token, url=url, qr_data_uri=data_uri, language=record.language
        )
        await store.set_stage(session, "takehome")
        await store.broadcast(
            session_id,
            {"type": "voice_note", "token": record.token, "qr_data_uri": data_uri},
        )

    elif op == "metric":
        latency = step.get("reply_latency_ms")
        session.state.metrics.last_reply_latency_ms = latency
        await store.broadcast(
            session_id,
            {
                "type": "metric",
                "reply_latency_ms": latency,
                "stages": step.get("stages", {}),
            },
        )

    elif op == "failover":
        await store.broadcast(
            session_id,
            {
                "type": "failover",
                "from": step.get("from", "indic"),
                "to": step.get("to", "multi_backup"),
                "gap_ms": step.get("gap_ms"),
            },
        )

    elif op == "error":
        await store.broadcast(
            session_id,
            {
                "type": "error",
                "code": step.get("code", "unknown"),
                "message": step.get("message", ""),
            },
        )

    elif op == "end":
        await store.set_stage(session, "ended")
        await store.broadcast(
            session_id,
            {"type": "session_ended", "reason": step.get("reason", "mock replay finished")},
        )

    else:
        raise MockScriptError(f"unknown mock op {op!r}")
