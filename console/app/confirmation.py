"""The gate — docs/04 §3.1. The single most important piece of the build.

`await_confirmation` long-polls for up to 25 s. It returns `confirmed` only when every line in
`prescription.lines` carries `confirmed: true`, and only then does it carry `readback_text`, which
is rendered here by `readback.py` from the confirmed RxLine fields alone.

The doctor's tap on `POST /api/sessions/{id}/rx/confirm-all` resolves the poll. That endpoint
refuses with 409 while any line is unconfirmed — the "read-back is dead until every line is
confirmed" promise lives on the server, not in CSS.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from . import config, readback
from .models import now_iso
from .sessions import Session, SessionStore

log = logging.getLogger("console.confirmation")

STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_REJECTED = "rejected"
# Duplicated in the tool's output enum (vaidyavaani-agent/tools/await_doctor_confirmation.yaml),
# where unmute checks them at compile time. Changing one of these breaks that build, which is the
# point. See docs/04 §3.1 invariant 4.
GATE_STATUSES = (STATUS_PENDING, STATUS_CONFIRMED, STATUS_REJECTED)


class ConfirmAllRejected(Exception):
    """Raised instead of locking a prescription that still has unconfirmed lines (→ 409)."""

    def __init__(self, unconfirmed: list[str]) -> None:
        self.unconfirmed = unconfirmed
        super().__init__(
            "every line must be confirmed before the read-back: unconfirmed "
            + ", ".join(unconfirmed)
        )


def _content_dir() -> Path:
    """Where readback/{ta,kn,hi}.yaml live. Resolved per call so tests can point it elsewhere."""
    return config.CONTENT_DIR


def readback_language(session: Session) -> str:
    lang = session.state.patient_language
    return lang if lang in readback.READBACK_LANGUAGES else ""


def poll_now(session: Session) -> dict[str, Any]:
    """The gate's answer at this instant, with no waiting. Shape per docs/04 §3.1."""
    if session.gate_outcome == STATUS_REJECTED:
        return {"status": STATUS_REJECTED, "reason": session.gate_reason or "doctor cancelled"}

    lines = session.state.prescription.lines
    every_line_confirmed = bool(lines) and all(ln.confirmed for ln in lines)

    if (
        session.gate_outcome == STATUS_CONFIRMED
        and every_line_confirmed
        and session.readback_text
    ):
        # invariant 2: readback_text rides on a confirmed response and on nothing else.
        return {"status": STATUS_CONFIRMED, "readback_text": session.readback_text}

    # invariant 1: anything short of every line confirmed is pending, with no readback_text.
    return {"status": STATUS_PENDING}


async def await_confirmation(
    session: Session, timeout: float | None = None
) -> dict[str, Any]:
    """Long-poll. Returns as soon as the doctor acts, or `pending` at timeout."""
    budget = config.CONFIRMATION_LONGPOLL_SECONDS if timeout is None else timeout
    deadline = time.monotonic() + budget

    while True:
        answer = poll_now(session)
        if answer["status"] != STATUS_PENDING:
            return answer
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"status": STATUS_PENDING}
        try:
            await asyncio.wait_for(session.gate_event.wait(), timeout=remaining)
        except (asyncio.TimeoutError, TimeoutError):
            return {"status": STATUS_PENDING}
        session.gate_event.clear()


async def confirm_all(session: Session, store: SessionStore) -> dict[str, Any]:
    """The doctor's tap. Raises ConfirmAllRejected (→ 409) if any line is unconfirmed."""
    unconfirmed = session.unconfirmed_line_ids()
    if unconfirmed or not session.state.prescription.lines:
        raise ConfirmAllRejected(unconfirmed or ["<no prescription lines>"])

    language = readback_language(session)
    if not language:
        raise readback.ReadbackError(
            "cannot render the read-back: patient_language is "
            f"{session.state.patient_language!r}; expected one of "
            f"{readback.READBACK_LANGUAGES}"
        )

    # The only place readback_text is ever assigned.
    text = readback.render(session.state.prescription.lines, language, _content_dir())

    session.readback_text = text
    session.state.prescription.all_confirmed = True
    session.state.prescription.confirmed_at = now_iso()
    session.gate_outcome = STATUS_CONFIRMED
    session.gate_reason = ""
    session.touch()
    session.gate_event.set()

    session_id = session.state.session_id
    await store.broadcast(
        session_id,
        {"type": "rx_locked", "confirmed_at": session.state.prescription.confirmed_at},
    )
    await store.set_stage(session, "readback")
    await store.broadcast(
        session_id, {"type": "readback_started", "text": text, "language": language}
    )
    log.info("prescription locked for %s (%d lines)", session_id, len(session.state.prescription.lines))
    return {"confirmed_at": session.state.prescription.confirmed_at, "readback_text": text}


async def reject(
    session: Session, store: SessionStore, reason: str = "doctor cancelled"
) -> dict[str, Any]:
    session.gate_outcome = STATUS_REJECTED
    session.gate_reason = reason
    session.readback_text = ""
    session.state.prescription.all_confirmed = False
    session.state.prescription.confirmed_at = None
    session.touch()
    session.gate_event.set()
    await store.set_stage(session, "prescribe")
    return {"ok": True, "status": STATUS_REJECTED, "reason": reason}


def reopen(session: Session) -> None:
    """A line was edited after a lock: the gate goes back to pending and the text is dropped."""
    if session.gate_outcome == STATUS_CONFIRMED:
        session.gate_outcome = None
    session.readback_text = ""
    session.state.prescription.all_confirmed = False
    session.state.prescription.confirmed_at = None
