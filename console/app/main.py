"""The Clinic Console — FastAPI on 127.0.0.1:8808.

Routes: docs/04 §3 (the agent's tools, in tool_api.py), §4 (the browser, here) and §5 (the
WebSocket, here). Bound to loopback only; the tunnel fronts Next.js, not this.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from . import config, confirmation, cost, metrics, mock, readback, tokens, voicenotes
from . import tool_api
from .models import RxLine, now_iso
from .sessions import Session, store

logging.basicConfig(
    level=os.environ.get("CONSOLE_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
)
log = logging.getLogger("console.main")

_mock_tasks: dict[str, asyncio.Task[None]] = {}


# ── content preflight ────────────────────────────────────────────────────────────────────────


class ContentMissing(RuntimeError):
    pass


def resolve_content_dir() -> Path:
    """The content directory, or a clear error naming what is missing.

    content/ belongs to the content-eval session and is the only copy. There is no snapshot
    inside console/ to fall back to, on purpose: a second copy of someone else's content drifts.
    """
    missing = [
        language
        for language in readback.READBACK_LANGUAGES
        if not (config.CONTENT_DIR / "readback" / f"{language}.yaml").exists()
    ]
    if missing:
        raise ContentMissing(
            f"No read-back template for {', '.join(missing)} in {config.CONTENT_DIR}. The "
            f"console cannot render a read-back without them, and it will not invent one.\n"
            f"Set CONSOLE_CONTENT_DIR to the directory that holds readback/{{ta,kn,hi}}.yaml."
        )
    return config.CONTENT_DIR


def preflight() -> None:
    """Fail clearly at startup rather than mysteriously at the gate."""
    resolve_content_dir()
    for language in readback.READBACK_LANGUAGES:
        readback.load_template(language, config.CONTENT_DIR)  # raises ReadbackError if malformed
    statuses = readback.review_status(config.CONTENT_DIR)
    log.info("read-back templates loaded from %s (review: %s)", config.CONTENT_DIR, statuses)
    unreviewed = sorted(lang for lang, status in statuses.items() if status != "signed_off")
    if unreviewed:
        log.warning(
            "read-back content is NOT native-reviewed for %s. Every rendered sentence is a "
            "draft; do not demo with review.status still pending "
            "(`python eval/score.py review-status` counts the open tags).",
            ", ".join(unreviewed),
        )

    if config.CONSOLE_TOKEN_IS_DEFAULT:
        log.warning(
            "CONSOLE_TOKEN is unset; using the development default. The agent's tool handlers "
            "must send the same value in X-Console-Token."
        )
    if not config.LIVEKIT_IS_CONFIGURED:
        log.warning(
            "LIVEKIT_API_KEY/LIVEKIT_API_SECRET are unset; minting tokens with the livekit-server "
            "dev defaults (devkey/secret)."
        )
    if config.MOCK:
        try:
            script = mock.load_script()
        except mock.MockScriptError as exc:
            log.error("--mock is on but the script is unusable: %s", exc)
        else:
            log.info(
                "mock mode: %s (%d steps)", config.MOCK_SCRIPT_PATH, len(script["steps"])
            )


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    preflight()
    store.start_sweeper()
    log.info(
        "clinic console %s listening on http://%s:%s (mock=%s)",
        config.CONSOLE_VERSION,
        config.HOST,
        config.PORT,
        config.MOCK,
    )
    try:
        yield
    finally:
        for task in list(_mock_tasks.values()):
            task.cancel()
        await store.stop_sweeper()
        for session_id in store.ids():
            store.purge(session_id, "server shutdown")


app = FastAPI(title="VaidyaVaani Clinic Console", version=config.CONSOLE_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    allow_origin_regex=r"https://.*\.trycloudflare\.com",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(tool_api.router)

browser = APIRouter(prefix="/api", tags=["browser"])


def _session(session_id: str) -> Session:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"unknown session {session_id}")
    return session


# ── §4 browser API ───────────────────────────────────────────────────────────────────────────


class CreateSessionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_language: str = ""
    identity: str = "clinic-tablet"


class LanguageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    side: str
    lang: str


class ConsentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    given: bool


class RejectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = "doctor cancelled"


@browser.post("/sessions")
async def create_session(body: CreateSessionBody | None = None) -> dict:
    body = body or CreateSessionBody()
    session = store.create(patient_language=body.patient_language)
    token = tokens.mint_join_token(session.room_name, body.identity)
    return {
        "session_id": session.state.session_id,
        "livekit_url": config.LIVEKIT_URL,
        "livekit_token": token,
        "room_name": session.room_name,
    }


@browser.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    return _session(session_id).state.model_dump()


@browser.post("/sessions/{session_id}/language")
async def set_language(session_id: str, body: LanguageBody) -> dict:
    session = _session(session_id)
    if body.side == "patient":
        if body.lang not in ("ta", "kn", "hi", "unsupported", ""):
            raise HTTPException(status_code=422, detail=f"bad patient language {body.lang!r}")
        session.state.patient_language = body.lang  # type: ignore[assignment]
        await store.broadcast(
            session_id, {"type": "lang_detected", "lang": body.lang, "confidence": 1.0}
        )
    elif body.side == "doctor":
        session.state.doctor_language = body.lang
    else:
        raise HTTPException(status_code=422, detail=f"bad side {body.side!r}")
    return {"ok": True, "state": session.state.model_dump()}


@browser.post("/sessions/{session_id}/consent")
async def set_consent(session_id: str, body: ConsentBody) -> dict:
    session = _session(session_id)
    session.state.consent.given = body.given
    session.state.consent.at = now_iso() if body.given else None
    if body.given and session.state.stage in ("start", "consent"):
        await store.set_stage(session, "interpret")
    await store.broadcast(
        session_id, {"type": "state_snapshot", "state": session.state.model_dump()}
    )
    return {"ok": True}


@browser.patch("/sessions/{session_id}/rx/{line_id}")
async def edit_line(session_id: str, line_id: str, patch: dict[str, Any]) -> dict:
    """Edit one line. Any RxLine field. Always clears `confirmed` — editing reopens the gate."""
    session = _session(session_id)
    line = session.line(line_id)
    if line is None:
        raise HTTPException(status_code=404, detail=f"unknown line {line_id}")
    forbidden = {"id"} & set(patch)
    if forbidden:
        raise HTTPException(status_code=422, detail="line ids are assigned by the console")
    merged = line.model_dump() | {k: v for k, v in patch.items() if k != "confirmed"}
    merged["confirmed"] = False
    try:
        updated = RxLine(**merged)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.state.prescription.lines[session.state.prescription.lines.index(line)] = updated
    confirmation.reopen(session)
    await store.line_updated(session, updated)
    if session.state.stage == "readback":
        await store.set_stage(session, "await_confirm")
    return updated.model_dump()


@browser.post("/sessions/{session_id}/rx/{line_id}/confirm")
async def confirm_line(session_id: str, line_id: str) -> dict:
    session = _session(session_id)
    line = session.line(line_id)
    if line is None:
        raise HTTPException(status_code=404, detail=f"unknown line {line_id}")
    line.confirmed = True
    await store.line_updated(session, line)
    return line.model_dump()


@browser.post("/sessions/{session_id}/rx/confirm-all")
async def confirm_all(session_id: str) -> dict:
    """The doctor's tap. 409 while any line is unconfirmed — the promise, on the server."""
    session = _session(session_id)
    try:
        result = await confirmation.confirm_all(session, store)
    except confirmation.ConfirmAllRejected as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "lines_unconfirmed",
                "message": str(exc),
                "unconfirmed": exc.unconfirmed,
            },
        ) from exc
    except readback.ReadbackError as exc:
        raise HTTPException(
            status_code=503, detail={"error": "readback_unavailable", "message": str(exc)}
        ) from exc
    return {"ok": True, **result}


@browser.post("/sessions/{session_id}/rx/reject")
async def reject_rx(session_id: str, body: RejectBody | None = None) -> dict:
    session = _session(session_id)
    return await confirmation.reject(session, store, (body or RejectBody()).reason)


@browser.post("/sessions/{session_id}/end")
async def end_session(session_id: str) -> dict:
    session = _session(session_id)
    await store.set_stage(session, "ended")
    await store.broadcast(session_id, {"type": "session_ended", "reason": "doctor ended"})
    task = _mock_tasks.pop(session_id, None)
    if task is not None:
        task.cancel()
    store.purge(session_id, "doctor ended")
    return {"ok": True, "purged": True}


@browser.get("/sessions/{session_id}/metrics")
async def session_metrics(session_id: str) -> dict:
    session = _session(session_id)
    summary = metrics.summarise(session_id=session_id)
    if summary["samples"] == 0 and not summary["source_present"]:
        # Nothing from unmute yet — fall back to the shipped sample so the HUD has shape. This is
        # our own hand-written log sample, not a copy of anyone else's content.
        summary = metrics.summarise(path=config.FIXTURE_DEV_LOG)
        summary["fixture"] = True
    session.state.metrics.reply_latency_p90_ms = summary["reply_latency_ms"]["p90"]
    session.state.metrics.last_reply_latency_ms = summary["reply_latency_ms"]["last"]
    summary["turns"] = len(session.state.turns)
    summary["ptt_side_disagreements"] = session.side_disagreements
    summary["ptt_frames"] = session.ptt_frames
    return summary


@browser.get("/cost")
async def get_cost(
    minutes: float = Query(10.0, ge=0, le=600),
    mode: str = Query("demo", pattern="^(demo|production)$"),
    session_id: str | None = Query(None),
    stt_audio_seconds: float | None = Query(None, ge=0),
    tts_audio_seconds: float | None = Query(None, ge=0),
) -> dict:
    """₹ per consultation. STT and TTS are priced from measured audio seconds (docs/02 §7.1).

    `mode=demo` leaves the platform bundle at $0, as a local LiveKit server really is;
    `mode=production` charges it per agent-minute. The response says which.
    """
    dev_log = config.DEV_LOG_PATH if config.DEV_LOG_PATH.exists() else config.FIXTURE_DEV_LOG
    return cost.estimate(
        minutes,
        mode=mode,
        stt_audio_seconds=stt_audio_seconds,
        tts_audio_seconds=tts_audio_seconds,
        dev_log=dev_log,
        session_id=session_id,
    )


@browser.get("/voicenote/{token}")
async def get_voice_note(token: str) -> Response:
    """The take-home WAV. One-time, TTL 30 min — the second request is a 404 by design."""
    record = voicenotes.store.take(token)
    if record is None:
        raise HTTPException(status_code=404, detail="voice note expired or already collected")
    return Response(
        content=record.wav,
        media_type="audio/wav",
        headers={
            "Content-Disposition": f'inline; filename="vaidyavaani-{record.token}.wav"',
            "Cache-Control": "no-store",
            "X-VaidyaVaani-Language": record.language,
        },
    )


# ── §3.1 the gate (a tool endpoint, under the /api/sessions prefix per the contract) ─────────


@browser.get("/sessions/{session_id}/confirmation", dependencies=[Depends(tool_api.require_console_token)])
async def await_doctor_confirmation(session_id: str) -> dict:
    session = _session(session_id)
    return await confirmation.await_confirmation(session)


app.include_router(browser)


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "ok": True,
        # `livekit` is a boolean on purpose: web-console's stub reads it as one.
        "livekit": config.LIVEKIT_IS_CONFIGURED,
        "livekit_url": config.LIVEKIT_URL,
        "console_version": config.CONSOLE_VERSION,
        "mock": config.MOCK,
        "sessions": len(store),
        "content_dir": str(config.CONTENT_DIR),
        "readback_review": readback.review_status(config.CONTENT_DIR),
        "voice_notes_held": len(voicenotes.store),
    }


# ── §5 WebSocket ─────────────────────────────────────────────────────────────────────────────


@app.websocket("/ws/sessions/{session_id}")
async def session_socket(socket: WebSocket, session_id: str) -> None:
    await socket.accept()
    session = store.get(session_id)
    if session is None:
        await socket.send_json(
            {"type": "error", "code": "unknown_session", "message": f"no session {session_id}"}
        )
        await socket.close(code=4404)
        return

    session.sockets.append(socket)
    session.disconnected_at = None
    await store.send_snapshot(session, socket)   # always the first frame

    if config.MOCK and session_id not in _mock_tasks:
        _mock_tasks[session_id] = asyncio.create_task(mock.replay(session, store))

    try:
        while True:
            frame = await socket.receive_json()
            session.touch()
            kind = frame.get("type")
            if kind == "ptt":
                session.ptt_frames += 1
                if frame.get("state") == "down":
                    session.ptt_side = frame.get("side")
                elif frame.get("state") == "up":
                    session.ptt_side = None
            elif kind == "ping":
                pass  # liveness only; §5 defines no pong frame
    except WebSocketDisconnect:
        pass
    except Exception:
        log.debug("websocket for %s closed unexpectedly", session_id, exc_info=True)
    finally:
        if socket in session.sockets:
            session.sockets.remove(socket)
        if not session.sockets:
            import time as _time

            session.disconnected_at = _time.monotonic()
            log.info(
                "browser gone for %s; purging in %.0fs unless it reconnects",
                session_id,
                config.DISCONNECT_GRACE_SECONDS,
            )


@app.exception_handler(ContentMissing)
async def _content_missing(_: Request, exc: ContentMissing) -> JSONResponse:  # pragma: no cover
    return JSONResponse(status_code=503, content={"error": "content_missing", "message": str(exc)})


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="console", description="VaidyaVaani Clinic Console")
    parser.add_argument("--mock", action="store_true", help="replay a canned consultation (docs/04 §7)")
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--reload", action="store_true", help="uvicorn autoreload")
    parser.add_argument(
        "--auto-confirm",
        type=float,
        default=None,
        metavar="SECONDS",
        help="mock only: tap confirm-all automatically after N seconds",
    )
    args = parser.parse_args(argv)

    if args.mock:
        config.MOCK = True
        os.environ["CONSOLE_MOCK"] = "1"
    if args.auto_confirm is not None:
        config.MOCK_AUTO_CONFIRM_SECONDS = args.auto_confirm
        os.environ["CONSOLE_MOCK_AUTO_CONFIRM"] = str(args.auto_confirm)
    config.PORT = args.port

    try:
        preflight()
    except (ContentMissing, readback.ReadbackError) as exc:
        print(f"\nstartup error: {exc}\n", file=sys.stderr)
        return 2

    import uvicorn

    uvicorn.run(
        "app.main:app" if args.reload else app,
        host=config.HOST,          # 127.0.0.1, never 0.0.0.0
        port=config.PORT,
        reload=args.reload,
        log_level=os.environ.get("CONSOLE_LOG_LEVEL", "info").lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
