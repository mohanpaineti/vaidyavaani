"""The take-home voice note: a token-keyed WAV held in memory, served once, TTL 30 minutes.

Nothing touches disk. The console does not synthesise speech itself — if the caller supplies
`audio_b64` (the agent's TTS render) we keep those bytes; otherwise we keep a short silent WAV
placeholder so the QR path is demonstrable end to end, and the note's text travels with it.
"""

from __future__ import annotations

import base64
import binascii
import io
import logging
import secrets
import struct
import time
import wave
from dataclasses import dataclass, field

import qrcode

from . import config

log = logging.getLogger("console.voicenotes")

MAX_AUDIO_BYTES = 8 * 1024 * 1024


@dataclass
class VoiceNoteRecord:
    token: str
    session_id: str
    language: str
    text: str
    wav: bytes
    created_at: float = field(default_factory=time.monotonic)
    served: bool = False


class VoiceNoteStore:
    def __init__(self) -> None:
        self._notes: dict[str, VoiceNoteRecord] = {}

    def create(
        self,
        session_id: str,
        text: str,
        language: str,
        audio_b64: str | None = None,
    ) -> VoiceNoteRecord:
        token = "vn_" + secrets.token_urlsafe(6)
        wav = _silent_wav()
        if audio_b64:
            try:
                decoded = base64.b64decode(audio_b64, validate=True)
            except (binascii.Error, ValueError):
                log.warning("voice note audio_b64 was not valid base64; using the placeholder")
            else:
                if len(decoded) > MAX_AUDIO_BYTES:
                    log.warning("voice note audio too large (%d bytes); using the placeholder",
                                len(decoded))
                else:
                    wav = decoded
        record = VoiceNoteRecord(
            token=token, session_id=session_id, language=language, text=text, wav=wav
        )
        self._notes[token] = record
        return record

    def take(self, token: str) -> VoiceNoteRecord | None:
        """Serve once: the record is removed as it is handed over."""
        self.sweep()
        record = self._notes.get(token)
        if record is None or record.served:
            return None
        record.served = True
        self._notes.pop(token, None)
        return record

    def peek(self, token: str) -> VoiceNoteRecord | None:
        self.sweep()
        return self._notes.get(token)

    def sweep(self, now: float | None = None) -> list[str]:
        now = time.monotonic() if now is None else now
        expired = [
            token
            for token, record in self._notes.items()
            if now - record.created_at >= config.VOICE_NOTE_TTL_SECONDS
        ]
        for token in expired:
            self._notes.pop(token, None)
        return expired

    def __len__(self) -> int:
        return len(self._notes)


def public_url(token: str) -> str:
    return f"{config.PUBLIC_URL.rstrip('/')}/api/voicenote/{token}"


def qr_data_uri(payload: str) -> str:
    """A PNG data URI for the phone to scan."""
    image = qrcode.make(payload)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _silent_wav(seconds: float = 0.4, rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(struct.pack("<h", 0) * int(rate * seconds))
    return buffer.getvalue()


store = VoiceNoteStore()
