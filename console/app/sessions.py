"""In-memory session store and the browser WebSocket hub.

No database. Nothing here is written to disk — the privacy posture is enforced by there being
nowhere to write. Sessions purge:

* when the last browser WebSocket drops (after a short grace, so a page reload is survivable),
* when the doctor ends the session,
* when the idle sweeper finds them untouched for `SESSION_IDLE_SECONDS`.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from . import config
from .models import Metrics, Prescription, RedFlag, RxLine, SessionState, Turn, now_iso

log = logging.getLogger("console.sessions")


@dataclass
class Session:
    state: SessionState
    room_name: str
    created_at: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)

    # The gate (docs/04 §3.1). Outcome is None until the doctor acts.
    gate_outcome: str | None = None            # "confirmed" | "rejected"
    gate_reason: str = ""
    readback_text: str = ""                    # rendered by readback.py, never set from outside
    gate_event: asyncio.Event = field(default_factory=asyncio.Event)

    ambiguities: list[str] = field(default_factory=list)
    sockets: list[Any] = field(default_factory=list)
    disconnected_at: float | None = None

    # Audit: the browser's push-to-talk side vs the language the agent detected (docs/04 §5).
    ptt_side: str | None = None
    ptt_frames: int = 0
    side_disagreements: int = 0

    _turn_seq: int = 0
    _rx_seq: int = 0
    _flag_seq: int = 0

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def next_turn_id(self) -> str:
        self._turn_seq += 1
        return f"t_{self._turn_seq}"

    def next_rx_id(self) -> str:
        self._rx_seq += 1
        return f"rx_{self._rx_seq}"

    def next_flag_id(self) -> str:
        self._flag_seq += 1
        return f"rf_{self._flag_seq}"

    def line(self, line_id: str) -> RxLine | None:
        for line in self.state.prescription.lines:
            if line.id == line_id:
                return line
        return None

    def unconfirmed_line_ids(self) -> list[str]:
        return [ln.id for ln in self.state.prescription.lines if not ln.confirmed]


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._sweeper: asyncio.Task[None] | None = None

    # ---- lifecycle -----------------------------------------------------------------

    def create(self, patient_language: str = "") -> Session:
        session_id = "s_" + secrets.token_hex(3)
        state = SessionState(
            session_id=session_id,
            patient_language=patient_language,  # type: ignore[arg-type]
            prescription=Prescription(),
            metrics=Metrics(),
        )
        session = Session(state=state, room_name=f"vaidyavaani-{session_id}")
        self._sessions[session_id] = session
        log.info("session created: %s", session_id)
        return session

    def get(self, session_id: str) -> Session | None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.touch()
        return session

    def purge(self, session_id: str, reason: str = "purged") -> None:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return
        # Resolve any gate waiter so the agent's long-poll returns instead of hanging.
        if session.gate_outcome is None:
            session.gate_outcome = "rejected"
            session.gate_reason = reason
        session.gate_event.set()
        session.state.turns.clear()
        session.state.red_flags.clear()
        session.state.prescription.lines.clear()
        log.info("session purged: %s (%s)", session_id, reason)

    def ids(self) -> list[str]:
        return list(self._sessions)

    def __len__(self) -> int:
        return len(self._sessions)

    # ---- the idle sweeper ----------------------------------------------------------

    def sweep(self, now: float | None = None) -> list[str]:
        now = time.monotonic() if now is None else now
        doomed: list[tuple[str, str]] = []
        for session_id, session in list(self._sessions.items()):
            disconnected = (
                session.disconnected_at is not None
                and not session.sockets
                and now - session.disconnected_at >= config.DISCONNECT_GRACE_SECONDS
            )
            if disconnected:
                doomed.append((session_id, "browser disconnected"))
            elif now - session.last_activity >= config.SESSION_IDLE_SECONDS:
                doomed.append((session_id, "idle"))
        for session_id, reason in doomed:
            self.purge(session_id, reason)
        return [session_id for session_id, _ in doomed]

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(config.SWEEP_INTERVAL_SECONDS)
            try:
                self.sweep()
            except Exception:  # pragma: no cover - the sweeper must never die
                log.exception("sweeper failed")

    def start_sweeper(self) -> None:
        if self._sweeper is None or self._sweeper.done():
            self._sweeper = asyncio.create_task(self._sweep_loop())

    async def stop_sweeper(self) -> None:
        if self._sweeper is not None:
            self._sweeper.cancel()
            try:
                await self._sweeper
            except (asyncio.CancelledError, Exception):
                pass
            self._sweeper = None

    # ---- WebSocket fan-out ---------------------------------------------------------

    async def broadcast(self, session_id: str, frame: dict[str, Any]) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        dead = []
        for socket in list(session.sockets):
            try:
                await socket.send_json(frame)
            except Exception:
                dead.append(socket)
        for socket in dead:
            if socket in session.sockets:
                session.sockets.remove(socket)

    # ---- mutations that every entry point funnels through --------------------------

    async def set_stage(self, session: Session, stage: str) -> None:
        session.state.stage = stage  # type: ignore[assignment]
        session.touch()
        await self.broadcast(session.state.session_id, {"type": "stage", "stage": stage})

    async def add_turn(self, session: Session, turn: Turn) -> Turn:
        turn.id = session.next_turn_id()
        if not turn.at:
            turn.at = now_iso()
        session.state.turns.append(turn)
        session.state.metrics.turns = len(session.state.turns)
        if turn.side == "patient" and session.ptt_side not in (None, "patient"):
            session.side_disagreements += 1
        session.touch()
        await self.broadcast(
            session.state.session_id, {"type": "turn", "turn": turn.model_dump()}
        )
        return turn

    async def add_red_flag(self, session: Session, flag: RedFlag) -> RedFlag:
        flag.id = session.next_flag_id()
        session.state.red_flags.append(flag)
        session.touch()
        await self.broadcast(
            session.state.session_id, {"type": "red_flag", "red_flag": flag.model_dump()}
        )
        return flag

    async def publish_draft(
        self, session: Session, lines: list[RxLine], ambiguities: list[str]
    ) -> list[str]:
        """Replace the draft prescription. Ids are assigned here — never by the agent."""
        session.state.prescription = Prescription(lines=[], all_confirmed=False, confirmed_at=None)
        session.readback_text = ""
        for line in lines:
            line.id = session.next_rx_id()
            line.confirmed = False
            session.state.prescription.lines.append(line)
        session.ambiguities = list(ambiguities)
        session.touch()
        await self.broadcast(
            session.state.session_id,
            {
                "type": "rx_draft",
                "lines": [ln.model_dump() for ln in session.state.prescription.lines],
                "ambiguities": session.ambiguities,
            },
        )
        return [ln.id for ln in session.state.prescription.lines]

    async def line_updated(self, session: Session, line: RxLine) -> None:
        session.touch()
        await self.broadcast(
            session.state.session_id, {"type": "rx_line_updated", "line": line.model_dump()}
        )

    async def send_snapshot(self, session: Session, socket: Any) -> None:
        await socket.send_json(
            {"type": "state_snapshot", "state": session.state.model_dump()}
        )


store = SessionStore()
