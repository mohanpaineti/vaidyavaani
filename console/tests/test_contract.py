"""The only thing standing between us and a dose that validates on one side but not the other.

docs/04 §2 gives the `RxLine` JSON shape; docs/04 §6 says the Pydantic model in
`vaidyavaani-agent/state.py` must match it field for field and constraint for constraint. This
test encodes §2 literally — the doc is the law — and compares both implementations against it:

* the console's own `app.models.RxLine`, always;
* the agent's `state.RxLine`, when `vaidyavaani-agent/state.py` exists. That file belongs to the
  unmute-agent session, so until it lands these cases **skip with a reason**. Once it exists they
  fail loudly on any drift.

`id`, `confidence` and `confirmed` are assigned by the console and are not expected on the agent
side (docs/04 §2: "`id` is assigned by the console, not the agent"). Every other field must match.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin

import pytest

from app import config
from app.models import RxLine as ConsoleRxLine
from app.models import Schedule as ConsoleSchedule
from tests.conftest import CONSOLE_TOKEN_HEADER

AGENT_STATE_PATH = Path(config.REPO_ROOT) / "vaidyavaani-agent" / "state.py"

# Fields the console owns. Absent from the agent's model by design.
CONSOLE_OWNED = {"id", "confidence", "confirmed"}

# ── docs/04 §2, transcribed ──────────────────────────────────────────────────────────────────

RXLINE_SPEC: dict[str, dict[str, Any]] = {
    # `string | null` since the 2026-10-17 contract fix: the agent cannot know an id the console
    # has not minted. The directional rule is asserted below rather than by nullability alone.
    "id": {"types": {"str"}, "optional": True},
    "drug_text": {"types": {"str"}, "optional": False},
    "strength_value": {"types": {"int", "float"}, "optional": True, "ge": 0, "le": 5000},
    "strength_unit": {"literal": {"mg", "ml", "g", "iu", "drops"}, "optional": True},
    "form": {
        "literal": {"tablet", "capsule", "syrup", "injection", "drops", "ointment"},
        "optional": True,
    },
    "schedule": {"types": {"Schedule"}, "optional": False},
    "food_relation": {"literal": {"before_food", "after_food", "with_food"}, "optional": True},
    "duration_days": {"types": {"int"}, "optional": True, "ge": 1, "le": 180},
    "notes": {"types": {"str"}, "optional": True},
    "confidence": {"types": {"int", "float"}, "optional": True},
    "confirmed": {"types": {"bool"}, "optional": False},
}

# docs/04 §2, changed 2026-10-17: schedule values are numbers in multiples of 0.5 from 0 to 4.
# `int | float` keeps a whole dose an int so the JSON stays `1`, not `1.0`.
SCHEDULE_SPEC: dict[str, dict[str, Any]] = {
    "morning": {"types": {"int", "float", "int | float"}, "optional": False, "ge": 0, "le": 4,
                "multiple_of": 0.5},
    "afternoon": {"types": {"int", "float", "int | float"}, "optional": False, "ge": 0, "le": 4,
                  "multiple_of": 0.5},
    "night": {"types": {"int", "float", "int | float"}, "optional": False, "ge": 0, "le": 4,
              "multiple_of": 0.5},
}

# What the type boundary must accept and reject, whichever side declares it. The spec's own
# words: "1, 0.5 and 1.5 are all legal; 0.25 and 1.3 are not and must be rejected".
LEGAL_DOSES = (0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4)
ILLEGAL_DOSES = (0.25, 1.3, -0.5, 4.5, 5, "one-ish")


# ── introspection ────────────────────────────────────────────────────────────────────────────


def _describe(model: Any) -> dict[str, dict[str, Any]]:
    described: dict[str, dict[str, Any]] = {}
    for name, field in model.model_fields.items():
        annotation = field.annotation
        optional = False
        if get_origin(annotation) is Union:
            args = [a for a in get_args(annotation) if a is not type(None)]
            optional = len(args) != len(get_args(annotation))
            annotation = args[0] if len(args) == 1 else Union[tuple(args)]  # type: ignore[valid-type]

        info: dict[str, Any] = {"optional": optional}
        if get_origin(annotation) is Literal:
            info["literal"] = set(get_args(annotation))
        else:
            type_name = getattr(annotation, "__name__", None)
            if type_name in (None, "Union", "UnionType"):
                # a union such as `int | float`, spelled the way the spec table spells it
                type_name = " | ".join(
                    getattr(arg, "__name__", str(arg)) for arg in get_args(annotation)
                ) or str(annotation)
            info["type"] = type_name

        for item in field.metadata:
            for constraint in ("ge", "le", "gt", "lt", "multiple_of"):
                if hasattr(item, constraint):
                    info[constraint] = getattr(item, constraint)
        described[name] = info
    return described


def _assert_matches_spec(model: Any, spec: dict[str, dict[str, Any]], label: str) -> None:
    actual = _describe(model)

    missing = sorted(set(spec) - set(actual))
    extra = sorted(set(actual) - set(spec))
    assert not missing, f"{label} is missing field(s) from docs/04 §2: {missing}"
    assert not extra, f"{label} has field(s) not in docs/04 §2: {extra}"

    for name, expected in spec.items():
        got = actual[name]
        if "literal" in expected:
            assert "literal" in got, f"{label}.{name} should be a Literal, got {got}"
            assert got["literal"] == expected["literal"], (
                f"{label}.{name} enum drifted: {sorted(got['literal'])} != "
                f"{sorted(expected['literal'])}"
            )
        else:
            assert got.get("type") in expected["types"], (
                f"{label}.{name} type drifted: {got.get('type')} not in {expected['types']}"
            )
        assert got["optional"] == expected["optional"], (
            f"{label}.{name} nullability drifted: optional={got['optional']}, "
            f"docs/04 says optional={expected['optional']}"
        )
        for constraint in ("ge", "le", "multiple_of"):
            if constraint in expected:
                assert got.get(constraint) == expected[constraint], (
                    f"{label}.{name} {constraint} drifted: {got.get(constraint)} != "
                    f"{expected[constraint]}"
                )


# ── the console side ─────────────────────────────────────────────────────────────────────────


def test_console_rxline_matches_docs_04():
    _assert_matches_spec(ConsoleRxLine, RXLINE_SPEC, "console RxLine")


def test_console_schedule_matches_docs_04():
    _assert_matches_spec(ConsoleSchedule, SCHEDULE_SPEC, "console Schedule")


def _assert_dose_boundary(schedule_model: Any, label: str) -> None:
    for dose in LEGAL_DOSES:
        schedule_model(morning=dose, afternoon=0, night=0)
    for dose in ILLEGAL_DOSES:
        try:
            schedule_model(morning=dose, afternoon=0, night=0)
        except Exception:
            continue
        pytest.fail(f"{label} accepted an illegal dose: {dose!r}")


def test_console_schedule_accepts_halves_and_rejects_quarters():
    _assert_dose_boundary(ConsoleSchedule, "console Schedule")


def test_console_schedule_rejects_a_boolean_dose():
    """Beyond the contract: pydantic would otherwise coerce True to a dose of 1."""
    with pytest.raises(Exception):
        ConsoleSchedule(morning=True, afternoon=0, night=0)


def test_an_agent_payload_may_omit_the_id():
    """The agent cannot populate an id the console has not minted yet (docs/04 §2)."""
    payload = {
        "drug_text": "Paracetamol",
        "schedule": {"morning": 1, "afternoon": 0, "night": 1},
        "food_relation": "after_food",
        "duration_days": 5,
    }
    assert ConsoleRxLine(**payload).id is None


def test_everything_the_console_emits_carries_an_id(client):
    """The other half of the directional rule: present on any line the console emits."""
    session_id = client.post("/api/sessions", json={"patient_language": "ta"}).json()["session_id"]
    client.post(
        "/api/tools/draft-rx",
        json={
            "session_id": session_id,
            "ambiguities": [],
            "lines": [
                {"drug_text": "Paracetamol", "schedule": {"morning": 1, "afternoon": 0, "night": 1}},
                {"drug_text": "ORS", "form": "syrup", "schedule": {"morning": 1, "afternoon": 1, "night": 1}},
            ],
        },
        headers=CONSOLE_TOKEN_HEADER,
    )
    state = client.get(f"/api/sessions/{session_id}").json()
    ids = [line["id"] for line in state["prescription"]["lines"]]
    assert ids == ["rx_1", "rx_2"]
    assert all(isinstance(line_id, str) and line_id for line_id in ids)

    # and on the frame the browser receives
    patched = client.patch(f"/api/sessions/{session_id}/rx/rx_1", json={"duration_days": 3})
    assert patched.json()["id"] == "rx_1"


def test_a_whole_dose_stays_an_int_in_the_json():
    """So the wire stays `{"morning": 1}` as every example in docs/04 §2 shows."""
    dumped = ConsoleSchedule(morning=1, afternoon=0, night=0.5).model_dump()
    assert dumped == {"morning": 1, "afternoon": 0, "night": 0.5}
    assert isinstance(dumped["morning"], int)
    assert isinstance(dumped["night"], float)


# ── the agent side ───────────────────────────────────────────────────────────────────────────


def _load_agent_state():
    if not AGENT_STATE_PATH.exists():
        pytest.skip(
            f"{AGENT_STATE_PATH} does not exist yet — it is owned by the unmute-agent session. "
            "This test asserts the RxLine contract across both sides and will run as soon as "
            "that file lands."
        )
    spec = importlib.util.spec_from_file_location("vaidyavaani_agent_state", AGENT_STATE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - a broken state.py must fail loudly
        pytest.fail(f"{AGENT_STATE_PATH} could not be imported: {exc!r}")
    return module


def test_agent_state_declares_rxline_and_schedule():
    module = _load_agent_state()
    assert hasattr(module, "RxLine"), f"{AGENT_STATE_PATH} has no RxLine"
    assert hasattr(module, "Schedule"), f"{AGENT_STATE_PATH} has no Schedule"


def test_agent_rxline_matches_docs_04_field_for_field():
    module = _load_agent_state()
    spec = {k: v for k, v in RXLINE_SPEC.items() if k not in CONSOLE_OWNED}
    present = set(_describe(module.RxLine))
    # Console-owned fields may be absent; if the agent declares one anyway, hold it to §2.
    for name in CONSOLE_OWNED & present:
        spec[name] = RXLINE_SPEC[name]
    _assert_matches_spec(module.RxLine, spec, f"{AGENT_STATE_PATH.name} RxLine")


def test_agent_schedule_matches_docs_04_constraint_for_constraint():
    module = _load_agent_state()
    _assert_matches_spec(module.Schedule, SCHEDULE_SPEC, f"{AGENT_STATE_PATH.name} Schedule")


def test_agent_schedule_accepts_halves_and_rejects_quarters():
    """The 2026-10-17 contract change has to land on both sides or a half dose splits them."""
    module = _load_agent_state()
    _assert_dose_boundary(module.Schedule, f"{AGENT_STATE_PATH.name} Schedule")


def test_agent_state_has_the_fields_docs_04_section_6_depends_on():
    module = _load_agent_state()
    assert hasattr(module, "State"), f"{AGENT_STATE_PATH} has no State"
    required = {
        "patient_language",
        "consent_given",
        "prescription",
        "prescription_confirmed",
        "readback_text",
        "teachback",
        "voice_note_token",
    }
    fields = set(module.State.model_fields)
    missing = sorted(required - fields)
    assert not missing, f"state.State is missing field(s) the console depends on: {missing}"


def test_agent_patient_language_literal_matches_docs_04():
    module = _load_agent_state()
    field = module.State.model_fields.get("patient_language")
    assert field is not None
    annotation = field.annotation
    if get_origin(annotation) is Union:
        annotation = [a for a in get_args(annotation) if a is not type(None)][0]
    assert get_origin(annotation) is Literal, "patient_language must be a Literal"
    assert set(get_args(annotation)) == {"ta", "kn", "hi", "unsupported", ""}


def test_a_console_rejected_dose_is_rejected_by_the_agent_model_too():
    """The same out-of-range values must fail on both sides, or the gate means nothing."""
    module = _load_agent_state()
    bad = [
        {"drug_text": "X", "duration_days": 500},
        {"drug_text": "X", "duration_days": 0},
        {"drug_text": "X", "strength_value": 9000},
        {"drug_text": "X", "schedule": {"morning": 10, "afternoon": 0, "night": 0}},
        {"drug_text": "X", "schedule": {"morning": 0.25, "afternoon": 0, "night": 0}},
        {"drug_text": "X", "schedule": {"morning": 1.3, "afternoon": 0, "night": 0}},
        {"drug_text": "X", "food_relation": "sometimes"},
        {"drug_text": "X", "form": "lozenge"},
        {"drug_text": "X", "strength_unit": "spoonful"},
    ]
    for payload in bad:
        with pytest.raises(Exception):
            ConsoleRxLine(**payload)
        with pytest.raises(Exception):
            module.RxLine(**payload)


def test_a_dose_from_the_agent_is_normalised_to_the_contract_shape():
    """The agent types schedule slots as `float`, so `1.0` arrives; docs/04 §2 shows `1`.

    The console normalises on the way in, so a card never reads "1.0 tablet" and the state the
    browser renders matches the contract's own examples.
    """
    schedule = ConsoleSchedule(morning=1.0, afternoon=0.0, night=0.5)
    assert schedule.model_dump() == {"morning": 1, "afternoon": 0, "night": 0.5}
    assert isinstance(schedule.morning, int)
    assert isinstance(schedule.night, float)
