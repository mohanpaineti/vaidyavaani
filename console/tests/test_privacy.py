"""The privacy posture: no database, nothing persisted but the demand log."""

from __future__ import annotations

import time

from app import config, demand_log, voicenotes
from tests.conftest import make_line


def test_ending_a_session_purges_it(client, store):
    session = store.create(patient_language="ta")
    session_id = session.state.session_id
    session.state.prescription.lines.append(make_line())

    assert client.post(f"/api/sessions/{session_id}/end").json()["purged"] is True

    assert store.get(session_id) is None
    assert client.get(f"/api/sessions/{session_id}").status_code == 404
    assert session.state.turns == [] and session.state.prescription.lines == []


def test_the_idle_sweeper_purges_an_untouched_session(store, monkeypatch):
    session = store.create()
    monkeypatch.setattr(config, "SESSION_IDLE_SECONDS", 0.0)
    assert store.sweep() == [session.state.session_id]
    assert store.get(session.state.session_id) is None


def test_a_disconnected_browser_purges_after_the_grace_period(store, monkeypatch):
    session = store.create()
    session.disconnected_at = time.monotonic()
    monkeypatch.setattr(config, "DISCONNECT_GRACE_SECONDS", 0.0)
    monkeypatch.setattr(config, "SESSION_IDLE_SECONDS", 10_000.0)
    assert store.sweep() == [session.state.session_id]


def test_a_reconnected_browser_is_not_purged(store, monkeypatch):
    session = store.create()
    session.disconnected_at = None
    monkeypatch.setattr(config, "DISCONNECT_GRACE_SECONDS", 0.0)
    monkeypatch.setattr(config, "SESSION_IDLE_SECONDS", 10_000.0)
    assert store.sweep() == []


def test_a_voice_note_serves_once(client, store):
    record = voicenotes.store.create("s_x", "take home text", "ta")
    first = client.get(f"/api/voicenote/{record.token}")
    assert first.status_code == 200
    assert first.headers["content-type"] == "audio/wav"
    assert first.content[:4] == b"RIFF"
    assert client.get(f"/api/voicenote/{record.token}").status_code == 404


def test_a_voice_note_expires(monkeypatch):
    record = voicenotes.store.create("s_x", "text", "ta")
    monkeypatch.setattr(config, "VOICE_NOTE_TTL_SECONDS", 0)
    assert record.token in voicenotes.store.sweep()
    assert voicenotes.store.take(record.token) is None


def test_the_demand_log_is_the_only_thing_written(tmp_path):
    path = tmp_path / "demand.jsonl"
    result = demand_log.log_unsupported_language("tulu", "patient from Mangaluru", path=path)
    assert result == {"ok": True, "second_language_offer": "kn"}
    records = demand_log.read_all(path)
    assert len(records) == 1
    assert records[0]["requested_language"] == "tulu"
    assert set(records[0]) == {"at", "requested_language", "note"}


def test_the_console_binds_loopback_only():
    assert config.HOST == "127.0.0.1"
