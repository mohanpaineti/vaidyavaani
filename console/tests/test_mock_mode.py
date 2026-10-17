"""Mock mode (docs/04 §7) — the canned consultation must replay end to end over the WebSocket.

The replay drives the same server code as the agent's tool calls, so these are the real frames:
`web/lib/console-ws.ts` sees nothing different between mock and real, which is the point.
"""

from __future__ import annotations

import copy

import pytest

from app import config, mock, readback


@pytest.fixture
def fast_mock(monkeypatch):
    """The shipped script with its waits removed, and the gate tapped automatically."""
    script = copy.deepcopy(mock.load_script(config.MOCK_SCRIPT_PATH))
    for step in script["steps"]:
        step["after_ms"] = 0
    monkeypatch.setattr(config, "MOCK", True)
    monkeypatch.setattr(config, "MOCK_AUTO_CONFIRM_SECONDS", 0.01)
    monkeypatch.setattr(mock, "load_script", lambda path=None: copy.deepcopy(script))
    return script


def test_the_shipped_script_is_valid(monkeypatch):
    script = mock.load_script(config.MOCK_SCRIPT_PATH)
    assert script["patient_language"] in ("ta", "kn", "hi")
    ops = {step.get("op") for step in script["steps"]}
    assert "await_confirm" in ops, "the mock must stop at the gate like the real thing"
    assert {"rx_draft", "turn", "red_flag", "teachback", "voice_note", "end"} <= ops


def test_a_missing_script_is_a_clear_error(tmp_path):
    with pytest.raises(mock.MockScriptError) as exc:
        mock.load_script(tmp_path / "nope.json")
    assert "not found" in str(exc.value)


def test_mock_replays_a_full_consultation(client, fast_mock):
    session_id = client.post("/api/sessions", json={}).json()["session_id"]

    frames = []
    with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
        while len(frames) < 200:
            frame = socket.receive_json()
            frames.append(frame)
            if frame["type"] == "session_ended":
                break

    kinds = [frame["type"] for frame in frames]
    assert kinds[0] == "state_snapshot"        # §5: always the first frame
    assert kinds[-1] == "session_ended"
    for expected in (
        "lang_detected", "stage", "partial", "turn", "red_flag", "metric", "failover",
        "rx_draft", "rx_line_updated", "rx_locked", "readback_started", "teachback_result",
        "voice_note",
    ):
        assert expected in kinds, f"the replay never produced a {expected} frame"

    # the gate was real: the lock came after every line was confirmed
    assert kinds.index("rx_locked") > kinds.index("rx_draft")
    assert kinds.index("readback_started") > kinds.index("rx_locked")

    readback_frame = next(f for f in frames if f["type"] == "readback_started")
    assert readback_frame["language"] == "ta"
    # two medicines, so each sentence is named, and the text is the template render
    text = readback_frame["text"]
    assert "Paracetamol" in text and "ORS" in text
    template = readback.load_template("ta", config.CONTENT_DIR)
    assert template.data["duration"]["day_words"][5] in text
    assert template.data["verb_phrase"]["tablet"] in text
    assert template.data["verb_phrase"]["syrup"] in text

    teachback_frame = next(f for f in frames if f["type"] == "teachback_result")
    # the canned patient read-back says "two days" for a five-day course
    assert teachback_frame["result"]["overall"] == "mismatch"
    assert "rx_1.duration" in teachback_frame["result"]["mismatched_fields"]

    stages = [f["stage"] for f in frames if f["type"] == "stage"]
    assert stages[-1] == "ended"
    for stage in ("consent", "interpret", "prescribe", "await_confirm", "readback", "takehome"):
        assert stage in stages, f"the replay never reached stage {stage}"


def test_the_gate_still_waits_for_a_real_tap_in_mock_mode(client, monkeypatch):
    """With auto-confirm off, the replay parks at await_confirm until the doctor taps."""
    script = copy.deepcopy(mock.load_script(config.MOCK_SCRIPT_PATH))
    for step in script["steps"]:
        step["after_ms"] = 0
    monkeypatch.setattr(config, "MOCK", True)
    monkeypatch.setattr(config, "MOCK_AUTO_CONFIRM_SECONDS", 0.0)
    monkeypatch.setattr(mock, "load_script", lambda path=None: copy.deepcopy(script))

    session_id = client.post("/api/sessions", json={}).json()["session_id"]
    with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
        kinds = []
        while len(kinds) < 40:
            kinds.append(socket.receive_json()["type"])
            if kinds[-1] == "rx_draft":
                break
        assert "rx_draft" in kinds
        # the draft is on screen and nothing clinical has been spoken
        assert "rx_locked" not in kinds and "readback_started" not in kinds

        state = client.get(f"/api/sessions/{session_id}").json()
        assert state["stage"] == "await_confirm"
        assert state["prescription"]["all_confirmed"] is False
        assert client.post(f"/api/sessions/{session_id}/rx/confirm-all").status_code == 409
