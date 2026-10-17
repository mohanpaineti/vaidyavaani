"""The endpoints the agent's local tool handlers call — docs/04 §3.

Every request carries `X-Console-Token`; a non-matching one is 401. Bodies are the exact shapes in
§2 and §3, including the injected `session_id`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import config, confirmation, demand_log, readback, teachback, voicenotes
from .models import BlankAsAbsent, LayTerm, RedFlag, RxLine, Turn, VoiceNote
from .sessions import Session, store

log = logging.getLogger("console.tool_api")

router = APIRouter(prefix="/api/tools", tags=["tools"])


def require_console_token(x_console_token: str | None = Header(default=None)) -> None:
    if x_console_token != config.CONSOLE_TOKEN:
        raise HTTPException(status_code=401, detail="bad or missing X-Console-Token")


def _session(session_id: str) -> Session:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"unknown session {session_id}")
    return session


class ToolBody(BlankAsAbsent):
    """Base for every tool body.

    unmute passes an omitted optional input as `""`, never absent (docs/04 §3), so nullable
    fields are coerced to None on the way in — see `BlankAsAbsent`.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str


class PushTurnBody(ToolBody):
    side: str
    original_text: str = ""
    english_text: str = ""
    detected_language: str = ""
    lay_terms: list[LayTerm] = Field(default_factory=list)
    negations: list[str] = Field(default_factory=list)


class RedFlagBody(ToolBody):
    phrase: str
    english: str
    severity: str
    source: str


class DraftRxBody(ToolBody):
    lines: list[RxLine]
    ambiguities: list[str] = Field(default_factory=list)


class TeachBackBody(ToolBody):
    patient_text: str = ""
    english_text: str = ""
    # Optional, and the only thing a model may supply: values, never verdicts.
    patient_said: dict[str, Any] | list[dict[str, Any]] | None = None


class VoiceNoteBody(ToolBody):
    text: str
    language: str
    audio_b64: str | None = None


class UnsupportedLanguageBody(ToolBody):
    requested_language: str
    note: str = ""


@router.post("/turn", dependencies=[Depends(require_console_token)])
async def push_turn(body: PushTurnBody) -> dict:
    session = _session(body.session_id)
    if body.side not in ("patient", "doctor", "agent"):
        raise HTTPException(status_code=422, detail=f"bad side {body.side!r}")
    turn = Turn(
        side=body.side,  # type: ignore[arg-type]
        original_text=body.original_text,
        english_text=body.english_text,
        detected_language=body.detected_language,
        lay_terms=body.lay_terms,
        negations=body.negations,
    )
    await store.add_turn(session, turn)
    if (
        body.detected_language
        and body.detected_language != session.state.patient_language
        and body.side == "patient"
        and body.detected_language in ("ta", "kn", "hi")
    ):
        session.state.patient_language = body.detected_language  # type: ignore[assignment]
        await store.broadcast(
            session.state.session_id,
            {"type": "lang_detected", "lang": body.detected_language, "confidence": None},
        )
    if session.state.stage in ("start", "consent"):
        await store.set_stage(session, "interpret")
    return {"ok": True, "turn_id": turn.id}


@router.post("/red-flag", dependencies=[Depends(require_console_token)])
async def raise_red_flag(body: RedFlagBody) -> dict:
    session = _session(body.session_id)
    if body.severity not in ("watch", "urgent"):
        raise HTTPException(status_code=422, detail=f"bad severity {body.severity!r}")
    if body.source not in ("keyword", "llm"):
        raise HTTPException(status_code=422, detail=f"bad source {body.source!r}")
    flag = RedFlag(
        phrase=body.phrase,
        english=body.english,
        severity=body.severity,  # type: ignore[arg-type]
        source=body.source,  # type: ignore[arg-type]
    )
    await store.add_red_flag(session, flag)
    return {"ok": True}


@router.post("/draft-rx", dependencies=[Depends(require_console_token)])
async def publish_draft_rx(body: DraftRxBody) -> dict:
    session = _session(body.session_id)
    line_ids = await store.publish_draft(session, body.lines, body.ambiguities)
    confirmation.reopen(session)
    await store.set_stage(session, "await_confirm")
    return {"ok": True, "line_ids": line_ids}


@router.post("/teachback", dependencies=[Depends(require_console_token)])
async def compare_teachback(body: TeachBackBody) -> dict:
    session = _session(body.session_id)
    lines = session.state.prescription.lines
    if not lines or not session.state.prescription.all_confirmed:
        raise HTTPException(
            status_code=409,
            detail="teach-back is compared against a confirmed prescription; none is locked",
        )
    result = teachback.compare(
        lines,
        patient_text=body.patient_text,
        english_text=body.english_text,
        patient_said=body.patient_said,
    )
    session.state.teachback = result
    await store.set_stage(session, "teachback")
    await store.broadcast(
        session.state.session_id,
        {"type": "teachback_result", "result": result.model_dump()},
    )
    return result.model_dump()


@router.post("/voice-note", dependencies=[Depends(require_console_token)])
async def create_voice_note(body: VoiceNoteBody) -> dict:
    session = _session(body.session_id)
    record = voicenotes.store.create(
        session_id=body.session_id,
        text=body.text,
        language=body.language,
        audio_b64=body.audio_b64,
    )
    url = voicenotes.public_url(record.token)
    data_uri = voicenotes.qr_data_uri(url)
    expires_at = (
        datetime.now(timezone.utc).timestamp() + config.VOICE_NOTE_TTL_SECONDS
    )
    session.state.voice_note = VoiceNote(
        token=record.token,
        url=url,
        qr_data_uri=data_uri,
        language=body.language,
        expires_at=datetime.fromtimestamp(expires_at, timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    )
    await store.set_stage(session, "takehome")
    await store.broadcast(
        session.state.session_id,
        {"type": "voice_note", "token": record.token, "qr_data_uri": data_uri},
    )
    return {"token": record.token, "url": url, "qr_data_uri": data_uri}


@router.post("/unsupported-language", dependencies=[Depends(require_console_token)])
async def log_unsupported_language(body: UnsupportedLanguageBody) -> dict:
    session = store.get(body.session_id)
    if session is not None:
        session.state.patient_language = "unsupported"
        await store.broadcast(
            body.session_id,
            {"type": "lang_detected", "lang": "unsupported", "confidence": None},
        )
    return demand_log.log_unsupported_language(body.requested_language, body.note)


@router.get("/_readback-languages", dependencies=[Depends(require_console_token)])
async def readback_languages() -> dict:
    """Which languages have a usable read-back template right now. Diagnostic, not in §3."""
    available = {}
    for language in readback.READBACK_LANGUAGES:
        try:
            readback.load_template(language, config.CONTENT_DIR)
            available[language] = True
        except readback.ReadbackError as exc:
            available[language] = str(exc)
    return {
        "content_dir": str(config.CONTENT_DIR),
        "languages": available,
        "review": readback.review_status(config.CONTENT_DIR),
    }
