"""Every endpoint in docs/04 §3–§4 and every server frame in §5, checked for shape."""

from __future__ import annotations

import pathlib

from app import config, tokens
from tests.conftest import CONSOLE_TOKEN_HEADER

SESSION_STATE_KEYS = {
    "session_id", "patient_language", "doctor_language", "consent", "stage", "turns",
    "red_flags", "prescription", "teachback", "voice_note", "metrics",
}

RX_LINE_KEYS = {
    "id", "drug_text", "strength_value", "strength_unit", "form", "schedule", "food_relation",
    "duration_days", "notes", "confidence", "confirmed",
}

DRAFT = {
    "lines": [
        {
            "drug_text": "Paracetamol",
            "strength_value": 500,
            "strength_unit": "mg",
            "form": "tablet",
            "schedule": {"morning": 1, "afternoon": 0, "night": 1},
            "food_relation": "after_food",
            "duration_days": 5,
            "notes": None,
            "confidence": 0.91,
        }
    ],
    "ambiguities": ["strength of 2nd drug not stated"],
}


def _create(client, language="ta"):
    body = client.post("/api/sessions", json={"patient_language": language}).json()
    return body


def test_create_session_returns_the_four_fields_and_a_real_livekit_token(client):
    body = _create(client)
    assert set(body) == {"session_id", "livekit_url", "livekit_token", "room_name"}
    claims = tokens.decode_unverified(body["livekit_token"])
    assert claims["video"]["room"] == body["room_name"]
    assert claims["video"]["roomJoin"] is True
    assert claims["iss"] == config.LIVEKIT_API_KEY


def test_the_join_token_dispatches_the_named_agent(client):
    """Without this the worker never joins and the patient talks to an empty room.

    The generated worker registers with an explicit `agent_name`, and LiveKit excludes a named
    worker from automatic dispatch — the room would get the default empty-name dispatch, which
    matches nothing. Nothing errors: the token parses, the room exists, the browser connects, and
    the only symptom is silence. Verified against a running LiveKit: with this claim the server
    creates a dispatch for `vaidyavaani-livekit` and the worker joins within ~4 s.
    """
    body = _create(client)
    claims = tokens.decode_unverified(body["livekit_token"])
    assert claims["roomConfig"] == {"agents": [{"agentName": config.LIVEKIT_AGENT_NAME}]}
    assert config.LIVEKIT_AGENT_NAME == "vaidyavaani-livekit"  # matches the compiled worker
    # the room is created by this join, so this join has to be allowed to configure it
    assert claims["video"]["roomCreate"] is True


def test_a_token_can_opt_out_of_dispatch():
    """A second joiner must not dispatch a second agent into a room that already has one."""
    claims = tokens.decode_unverified(
        tokens.mint_join_token("vaidyavaani-s_x", "observer", agent_name="")
    )
    assert "roomConfig" not in claims


def test_the_agent_name_is_not_hardcoded_in_tokens_py():
    """One source of truth: config, defaulted from the compiled worker, overridable by env."""
    source = (pathlib.Path(__file__).resolve().parent.parent / "app" / "tokens.py").read_text()
    assert "vaidyavaani-livekit" not in source


def test_get_session_returns_the_session_state_shape(client):
    session_id = _create(client)["session_id"]
    state = client.get(f"/api/sessions/{session_id}").json()
    assert set(state) == SESSION_STATE_KEYS
    assert state["stage"] == "start"
    assert state["prescription"] == {"lines": [], "all_confirmed": False, "confirmed_at": None}
    assert state["metrics"] == {
        "turns": 0, "reply_latency_p90_ms": None, "last_reply_latency_ms": None
    }


def test_healthz(client):
    body = client.get("/healthz").json()
    assert body["ok"] is True
    assert body["livekit"] is False  # no LIVEKIT_API_KEY in the test env
    assert body["livekit_url"] == config.LIVEKIT_URL
    assert body["console_version"] == config.CONSOLE_VERSION
    # the HUD can tell a judge whether the spoken strings are native-reviewed yet
    assert set(body["readback_review"]) == {"ta", "kn", "hi"}


def test_tool_endpoints_require_the_console_token(client):
    session_id = _create(client)["session_id"]
    for path, payload in [
        ("/api/tools/turn", {"session_id": session_id, "side": "patient"}),
        ("/api/tools/red-flag", {"session_id": session_id, "phrase": "x", "english": "y",
                                 "severity": "urgent", "source": "keyword"}),
        ("/api/tools/draft-rx", {"session_id": session_id, **DRAFT}),
        ("/api/tools/teachback", {"session_id": session_id, "patient_text": "", "english_text": ""}),
        ("/api/tools/voice-note", {"session_id": session_id, "text": "x", "language": "ta"}),
        ("/api/tools/unsupported-language", {"session_id": session_id,
                                             "requested_language": "tulu", "note": ""}),
    ]:
        assert client.post(path, json=payload).status_code == 401, path
        assert client.post(
            path, json=payload, headers={"X-Console-Token": "wrong"}
        ).status_code == 401, path


def test_push_turn_assigns_the_id(client):
    session_id = _create(client)["session_id"]
    body = client.post(
        "/api/tools/turn",
        json={
            "session_id": session_id,
            "side": "patient",
            "original_text": "காய்ச்சல் மூன்று நாள்",
            "english_text": "Fever for three days",
            "detected_language": "ta",
            "lay_terms": [{"said": "sugar", "likely_means": "diabetes"}],
            "negations": ["no chest pain"],
        },
        headers=CONSOLE_TOKEN_HEADER,
    ).json()
    assert body == {"ok": True, "turn_id": "t_1"}


def test_draft_rx_assigns_line_ids_and_clears_confirmed(client):
    session_id = _create(client)["session_id"]
    body = client.post(
        "/api/tools/draft-rx", json={"session_id": session_id, **DRAFT},
        headers=CONSOLE_TOKEN_HEADER,
    ).json()
    assert body == {"ok": True, "line_ids": ["rx_1"]}
    state = client.get(f"/api/sessions/{session_id}").json()
    assert set(state["prescription"]["lines"][0]) == RX_LINE_KEYS
    assert state["prescription"]["lines"][0]["confirmed"] is False
    assert state["stage"] == "await_confirm"


def test_an_agent_supplied_line_id_is_overwritten(client):
    session_id = _create(client)["session_id"]
    payload = {"session_id": session_id, "ambiguities": [],
               "lines": [dict(DRAFT["lines"][0], id="rx_HACKED")]}
    client.post("/api/tools/draft-rx", json=payload, headers=CONSOLE_TOKEN_HEADER)
    state = client.get(f"/api/sessions/{session_id}").json()
    assert state["prescription"]["lines"][0]["id"] == "rx_1"


def test_red_flag_and_unsupported_language(client):
    session_id = _create(client)["session_id"]
    assert client.post(
        "/api/tools/red-flag",
        json={"session_id": session_id, "phrase": "நடுக்கம்", "english": "shivering with fever",
              "severity": "urgent", "source": "keyword"},
        headers=CONSOLE_TOKEN_HEADER,
    ).json() == {"ok": True}

    body = client.post(
        "/api/tools/unsupported-language",
        json={"session_id": session_id, "requested_language": "tulu", "note": ""},
        headers=CONSOLE_TOKEN_HEADER,
    ).json()
    assert body == {"ok": True, "second_language_offer": "kn"}
    assert client.get(f"/api/sessions/{session_id}").json()["patient_language"] == "unsupported"


def test_teachback_tool_refuses_before_the_prescription_is_locked(client):
    session_id = _create(client)["session_id"]
    client.post("/api/tools/draft-rx", json={"session_id": session_id, **DRAFT},
                headers=CONSOLE_TOKEN_HEADER)
    response = client.post(
        "/api/tools/teachback",
        json={"session_id": session_id, "patient_text": "…", "english_text": "two days"},
        headers=CONSOLE_TOKEN_HEADER,
    )
    assert response.status_code == 409


def test_teachback_tool_returns_the_result_shape(client):
    session_id = _create(client)["session_id"]
    client.post("/api/tools/draft-rx", json={"session_id": session_id, **DRAFT},
                headers=CONSOLE_TOKEN_HEADER)
    client.post(f"/api/sessions/{session_id}/rx/rx_1/confirm")
    client.post(f"/api/sessions/{session_id}/rx/confirm-all")

    body = client.post(
        "/api/tools/teachback",
        json={"session_id": session_id, "patient_text": "…",
              "english_text": "One in the morning, one at night, after food, for two days."},
        headers=CONSOLE_TOKEN_HEADER,
    ).json()

    assert set(body) == {"overall", "per_line", "mismatched_fields", "simplest_restatement"}
    assert body["overall"] == "mismatch"
    assert body["mismatched_fields"] == ["rx_1.duration"]
    assert set(body["per_line"][0]) == {
        "line_id", "morning", "afternoon", "night", "duration", "food_relation", "patient_said"
    }


def test_voice_note_tool_returns_token_url_and_qr(client):
    session_id = _create(client)["session_id"]
    body = client.post(
        "/api/tools/voice-note",
        json={"session_id": session_id, "text": "take home", "language": "ta"},
        headers=CONSOLE_TOKEN_HEADER,
    ).json()
    assert set(body) == {"token", "url", "qr_data_uri"}
    assert body["token"].startswith("vn_")
    assert body["qr_data_uri"].startswith("data:image/png;base64,")
    assert body["token"] in body["url"]


def test_language_and_consent_overrides(client):
    session_id = _create(client, language="")["session_id"]
    assert client.post(f"/api/sessions/{session_id}/language",
                       json={"side": "patient", "lang": "kn"}).status_code == 200
    assert client.post(f"/api/sessions/{session_id}/language",
                       json={"side": "patient", "lang": "te"}).status_code == 422
    assert client.post(f"/api/sessions/{session_id}/consent",
                       json={"given": True}).json() == {"ok": True}
    state = client.get(f"/api/sessions/{session_id}").json()
    assert state["patient_language"] == "kn"
    assert state["consent"]["given"] is True and state["consent"]["at"]


def test_patch_validates_against_the_rxline_type_system(client):
    session_id = _create(client)["session_id"]
    client.post("/api/tools/draft-rx", json={"session_id": session_id, **DRAFT},
                headers=CONSOLE_TOKEN_HEADER)
    for bad in ({"duration_days": 500}, {"schedule": {"morning": 9, "afternoon": 0, "night": 0}},
                {"strength_value": 9000}, {"form": "lozenge"}, {"food_relation": "sometimes"}):
        assert client.patch(f"/api/sessions/{session_id}/rx/rx_1", json=bad).status_code == 422
    assert client.patch(f"/api/sessions/{session_id}/rx/rx_1",
                        json={"id": "rx_9"}).status_code == 422
    good = client.patch(f"/api/sessions/{session_id}/rx/rx_1", json={"duration_days": 7})
    assert good.json()["duration_days"] == 7


def test_unknown_session_is_404(client):
    assert client.get("/api/sessions/s_nope").status_code == 404
    assert client.post("/api/sessions/s_nope/rx/confirm-all").status_code == 404
    assert client.get(
        "/api/sessions/s_nope/confirmation", headers=CONSOLE_TOKEN_HEADER
    ).status_code == 404


# ── §5 frames ────────────────────────────────────────────────────────────────────────────────


def test_first_frame_is_always_a_state_snapshot(client):
    session_id = _create(client)["session_id"]
    with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
        frame = socket.receive_json()
        assert frame["type"] == "state_snapshot"
        assert set(frame["state"]) == SESSION_STATE_KEYS


def test_an_unknown_session_gets_an_error_frame(client):
    with client.websocket_connect("/ws/sessions/s_nope") as socket:
        frame = socket.receive_json()
        assert frame["type"] == "error"
        assert frame["code"] == "unknown_session"


def test_the_frames_a_consultation_produces(client):
    session_id = _create(client)["session_id"]
    with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
        assert socket.receive_json()["type"] == "state_snapshot"

        socket.send_json({"type": "ptt", "side": "patient", "state": "down"})
        socket.send_json({"type": "ping"})

        client.post(
            "/api/tools/turn",
            json={"session_id": session_id, "side": "patient", "original_text": "காய்ச்சல்",
                  "english_text": "fever", "detected_language": "ta"},
            headers=CONSOLE_TOKEN_HEADER,
        )
        turn = socket.receive_json()
        assert turn["type"] == "turn" and turn["turn"]["id"] == "t_1"
        assert socket.receive_json()["type"] == "stage"

        client.post(
            "/api/tools/red-flag",
            json={"session_id": session_id, "phrase": "நடுக்கம்", "english": "shivering",
                  "severity": "urgent", "source": "keyword"},
            headers=CONSOLE_TOKEN_HEADER,
        )
        assert socket.receive_json()["type"] == "red_flag"

        client.post("/api/tools/draft-rx", json={"session_id": session_id, **DRAFT},
                    headers=CONSOLE_TOKEN_HEADER)
        draft = socket.receive_json()
        assert draft["type"] == "rx_draft"
        assert draft["ambiguities"] == DRAFT["ambiguities"]
        assert socket.receive_json() == {"type": "stage", "stage": "await_confirm"}

        client.post(f"/api/sessions/{session_id}/rx/rx_1/confirm")
        assert socket.receive_json()["type"] == "rx_line_updated"

        client.post(f"/api/sessions/{session_id}/rx/confirm-all")
        locked = socket.receive_json()
        assert locked["type"] == "rx_locked" and locked["confirmed_at"]
        assert socket.receive_json() == {"type": "stage", "stage": "readback"}
        readback_frame = socket.receive_json()
        assert readback_frame["type"] == "readback_started"
        assert readback_frame["language"] == "ta"
        assert readback_frame["text"]

        client.post(
            "/api/tools/teachback",
            json={"session_id": session_id, "patient_text": "…",
                  "english_text": "one in the morning, one at night, after food, two days"},
            headers=CONSOLE_TOKEN_HEADER,
        )
        assert socket.receive_json() == {"type": "stage", "stage": "teachback"}
        result = socket.receive_json()
        assert result["type"] == "teachback_result"
        assert result["result"]["overall"] == "mismatch"

        client.post("/api/tools/voice-note",
                    json={"session_id": session_id, "text": "take home", "language": "ta"},
                    headers=CONSOLE_TOKEN_HEADER)
        assert socket.receive_json() == {"type": "stage", "stage": "takehome"}
        note = socket.receive_json()
        assert note["type"] == "voice_note" and note["token"].startswith("vn_")

        client.post(f"/api/sessions/{session_id}/end")
        assert socket.receive_json() == {"type": "stage", "stage": "ended"}
        assert socket.receive_json() == {"type": "session_ended", "reason": "doctor ended"}


# ── unmute passes an omitted optional input as "" (docs/04 §3) ───────────────────────────────
#
# unmute builds every tool call by keyword, every time, so an optional property is always
# supplied — as an empty string when the model omits it. The console coerces "" to None at the
# boundary, or `notes` is stored as "" instead of null and an optional enum fails validation.
# This only ever shows up on a live call, so it is tested here.


def test_an_omitted_optional_rxline_field_arrives_as_an_empty_string_and_is_stored_as_null(client):
    session_id = _create(client)["session_id"]

    response = client.post(
        "/api/tools/draft-rx",
        json={
            "session_id": session_id,
            "ambiguities": [],
            "lines": [
                {
                    "drug_text": "Paracetamol",
                    "schedule": {"morning": 1, "afternoon": 0, "night": 1},
                    # every optional field as unmute actually sends it when the model omits it
                    "strength_value": "",
                    "strength_unit": "",
                    "form": "",
                    "food_relation": "",
                    "duration_days": "",
                    "notes": "",
                    "confidence": "",
                }
            ],
        },
        headers=CONSOLE_TOKEN_HEADER,
    )

    assert response.status_code == 200, response.text
    line = client.get(f"/api/sessions/{session_id}").json()["prescription"]["lines"][0]
    for field in ("strength_value", "strength_unit", "form", "food_relation", "duration_days",
                  "notes", "confidence"):
        assert line[field] is None, f"{field} was stored as {line[field]!r}, not null"
    assert line["id"] == "rx_1"
    assert line["drug_text"] == "Paracetamol"


def test_an_empty_string_optional_still_renders_a_readback(client):
    """The null-form path: a line with no form or food relation still reaches the patient."""
    session_id = _create(client)["session_id"]
    client.post(
        "/api/tools/draft-rx",
        json={
            "session_id": session_id,
            "ambiguities": [],
            "lines": [{"drug_text": "Paracetamol", "form": "", "food_relation": "",
                       "schedule": {"morning": 1, "afternoon": 0, "night": 0},
                       "duration_days": 5, "notes": ""}],
        },
        headers=CONSOLE_TOKEN_HEADER,
    )
    client.post(f"/api/sessions/{session_id}/rx/rx_1/confirm")
    confirmed = client.post(f"/api/sessions/{session_id}/rx/confirm-all")
    assert confirmed.status_code == 200
    assert confirmed.json()["readback_text"]


def test_an_omitted_optional_tool_input_arrives_as_an_empty_string(client):
    session_id = _create(client)["session_id"]

    # log_unsupported_language's `note`
    assert client.post(
        "/api/tools/unsupported-language",
        json={"session_id": session_id, "requested_language": "tulu", "note": ""},
        headers=CONSOLE_TOKEN_HEADER,
    ).status_code == 200

    # create_voice_note's optional audio_b64
    note = client.post(
        "/api/tools/voice-note",
        json={"session_id": session_id, "text": "take home", "language": "ta", "audio_b64": ""},
        headers=CONSOLE_TOKEN_HEADER,
    )
    assert note.status_code == 200
    assert note.json()["token"].startswith("vn_")


def test_compare_teachback_tolerates_an_empty_patient_said(client):
    """`patient_said` is an optional object, so unmute sends "" when the model omits it."""
    session_id = _create(client)["session_id"]
    client.post("/api/tools/draft-rx", json={"session_id": session_id, **DRAFT},
                headers=CONSOLE_TOKEN_HEADER)
    client.post(f"/api/sessions/{session_id}/rx/rx_1/confirm")
    client.post(f"/api/sessions/{session_id}/rx/confirm-all")

    response = client.post(
        "/api/tools/teachback",
        json={
            "session_id": session_id,
            "patient_text": "…",
            "english_text": "one in the morning, one at night, after food, for two days",
            "patient_said": "",
        },
        headers=CONSOLE_TOKEN_HEADER,
    )

    assert response.status_code == 200, response.text
    # it fell back to the console's own extraction rather than failing validation
    assert response.json()["mismatched_fields"] == ["rx_1.duration"]
