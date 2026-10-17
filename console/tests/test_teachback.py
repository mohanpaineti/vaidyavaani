"""Teach-back — the five seeded wrong read-backs must all come back as mismatches.

A model supplies only what the patient said. Every verdict below is computed by
`app/teachback.py` in Python, and the numbers are compared arithmetically.
"""

from __future__ import annotations

import pytest

from app import teachback
from app.models import Schedule
from tests.conftest import make_line

# The confirmed prescription under test: 1 tablet morning + 1 tablet night, after food, 5 days.
CONFIRMED = dict(
    id="rx_1",
    schedule=Schedule(morning=1, afternoon=0, night=1),
    food_relation="after_food",
    duration_days=5,
    confirmed=True,
)


def line():
    return make_line(**CONFIRMED)


# (name, what the patient said in English, the field that must be flagged)
WRONG_READBACKS = [
    (
        "duration halved",
        "One tablet in the morning and one at night after food for two days.",
        "rx_1.duration",
    ),
    (
        "morning dose doubled",
        "Two tablets in the morning and one at night after food for five days.",
        "rx_1.morning",
    ),
    (
        "night dose dropped",
        "One tablet in the morning, nothing at night, after food for five days.",
        "rx_1.night",
    ),
    (
        "food relation inverted",
        "One tablet in the morning and one at night before food for five days.",
        "rx_1.food_relation",
    ),
    (
        "an afternoon dose invented",
        "One in the morning, one in the afternoon and one at night after food for five days.",
        "rx_1.afternoon",
    ),
]


@pytest.mark.parametrize("name,said,expected_field", WRONG_READBACKS)
def test_five_wrong_readbacks_are_all_caught(name, said, expected_field):
    result = teachback.compare([line()], patient_text="…", english_text=said)

    assert result.overall == "mismatch", f"{name} was not flagged: {result}"
    assert expected_field in result.mismatched_fields, f"{name}: {result.mismatched_fields}"
    assert result.simplest_restatement, f"{name} produced no restatement"


def test_a_correct_readback_matches():
    result = teachback.compare(
        [line()],
        english_text="One tablet in the morning and one tablet at night, after food, for five days.",
    )

    assert result.overall == "match"
    assert result.mismatched_fields == []
    assert result.simplest_restatement == ""
    per_line = result.per_line[0]
    assert per_line.morning == "match"
    assert per_line.night == "match"
    assert per_line.duration == "match"
    assert per_line.food_relation == "match"


def test_digits_and_words_compare_the_same_way():
    words = teachback.compare([line()], english_text="1 in the morning, 1 at night, after food for 5 days.")
    assert words.overall == "match"


def test_numbers_are_compared_arithmetically_not_as_strings():
    confirmed = make_line(duration_days=5, confirmed=True)
    result = teachback.compare([confirmed], english_text="for 05 days, one morning, one night, after food")
    assert result.per_line[0].duration == "match"


def test_unsaid_fields_are_not_mentioned_rather_than_mismatched():
    result = teachback.compare([line()], english_text="I take the tablets.")

    per_line = result.per_line[0]
    assert per_line.duration == "not_mentioned"
    assert per_line.food_relation == "not_mentioned"
    assert result.overall in ("not_attempted", "match")
    assert result.mismatched_fields == []


def test_a_slot_with_no_dose_is_not_mentioned_when_the_patient_skips_it():
    result = teachback.compare(
        [line()], english_text="One in the morning and one at night, after food, for five days."
    )
    assert result.per_line[0].afternoon == "not_mentioned"


def test_verdicts_come_from_the_console_even_when_a_model_supplies_values():
    """`patient_said` carries values only — the verdicts are still ours."""
    result = teachback.compare(
        [line()],
        patient_said={"schedule": {"morning": 1, "night": 1}, "duration_days": 2,
                      "food_relation": "after_food"},
    )
    assert result.overall == "mismatch"
    assert result.mismatched_fields == ["rx_1.duration"]
    assert result.simplest_restatement == "Five days, not two days."


def test_two_lines_are_attributed_by_drug_name():
    paracetamol = make_line(id="rx_1", drug_text="Paracetamol", confirmed=True,
                            schedule=Schedule(morning=1, night=1), duration_days=5,
                            food_relation="after_food")
    ors = make_line(id="rx_2", drug_text="ORS", form="syrup", strength_value=None,
                    strength_unit=None, confirmed=True,
                    schedule=Schedule(morning=1, afternoon=1, night=1), duration_days=3,
                    food_relation="with_food")

    result = teachback.compare(
        [paracetamol, ors],
        english_text=(
            "Paracetamol one in the morning and one at night after food for five days. "
            "ORS one in the morning, one in the afternoon, one at night with food for two days."
        ),
    )

    assert result.overall == "mismatch"
    assert result.mismatched_fields == ["rx_2.duration"]


def test_no_prescription_means_not_attempted():
    assert teachback.compare([]).overall == "not_attempted"


def test_extraction_is_deterministic():
    said = "Two tablets in the morning, nothing in the afternoon, one at night, after food for 5 days"
    first = teachback.extract_patient_said(said)
    assert first == teachback.extract_patient_said(said)
    assert first["schedule"] == {"morning": 2, "afternoon": 0, "night": 1}
    assert first["duration_days"] == 5
    assert first["food_relation"] == "after_food"


# ── content-eval's seeded cases ──────────────────────────────────────────────────────────────
#
# eval/fixtures/teachback_cases.json holds the five deliberately-wrong read-backs plus a CONTROL
# that must NOT flag: if the control flags, the comparator over-flags and the 5/5 number is
# worthless. These run against the fixture snapshot, and against the real eval/ file once it
# lands.

import json  # noqa: E402
from pathlib import Path  # noqa: E402

from app import config  # noqa: E402

from app.models import RxLine  # noqa: E402

# The seeded cases live in eval/, owned by the content-eval session, and are read from there —
# never from a copy under console/. A snapshot of someone else's fixture drifts, and a stale one
# already cost two sessions a round trip chasing a failure it manufactured.
SEEDED_CASES = Path(config.REPO_ROOT) / "eval" / "fixtures" / "teachback_cases.json"

requires_seeded_cases = pytest.mark.skipif(
    not SEEDED_CASES.exists(),
    reason=f"{SEEDED_CASES} not present — owned by the content-eval session",
)


def _load_cases(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def _run_case(case: dict) -> None:
    confirmed = RxLine(**dict(case["confirmed"], confirmed=True))
    result = teachback.compare([confirmed], patient_said=case["patient_said"])

    assert result.overall == case["expect_overall"], (
        f"{case['id']} ({case['why_wrong']}): overall {result.overall!r}, "
        f"expected {case['expect_overall']!r}"
    )
    assert result.mismatched_fields == case["expect_mismatched_fields"], (
        f"{case['id']}: {result.mismatched_fields} != {case['expect_mismatched_fields']}"
    )
    if case["expect_overall"] == "mismatch":
        assert result.simplest_restatement, f"{case['id']} produced no restatement"
    else:
        assert result.simplest_restatement == ""


@requires_seeded_cases
@pytest.mark.parametrize(
    "case", _load_cases(SEEDED_CASES) or [None], ids=[c["id"] for c in _load_cases(SEEDED_CASES)] or ["none"]
)
def test_content_eval_seeded_cases(case):
    _run_case(case)


@requires_seeded_cases
def test_the_catch_rate_is_five_out_of_five_and_the_control_does_not_flag():
    """The number that goes on the slide, recomputed from eval/fixtures/ every run.

    5/5 alone proves nothing — a comparator that flags everything scores 5/5 too. The control
    case is what makes it meaningful, so it is counted here in the same assertion.
    """
    cases = _load_cases(SEEDED_CASES)
    wrong = [case for case in cases if case["expect_overall"] == "mismatch"]
    controls = [case for case in cases if case["expect_overall"] == "match"]
    assert len(wrong) == 5, "docs/01 §7 seeds five wrong read-backs"
    assert len(controls) >= 1, "and at least one control that must not flag"

    caught = 0
    for case in wrong:
        confirmed = RxLine(**dict(case["confirmed"], confirmed=True))
        result = teachback.compare([confirmed], patient_said=case["patient_said"])
        if result.overall == "mismatch":
            caught += 1
    false_alarms = 0
    for case in controls:
        confirmed = RxLine(**dict(case["confirmed"], confirmed=True))
        result = teachback.compare([confirmed], patient_said=case["patient_said"])
        if result.overall != "match":
            false_alarms += 1

    assert caught == len(wrong), f"catch rate {caught}/{len(wrong)}, not {len(wrong)}/{len(wrong)}"
    assert false_alarms == 0, f"{false_alarms} control case(s) flagged — the comparator over-flags"


# ── half doses (docs/04 §2, changed 2026-10-17) ──────────────────────────────────────────────
#
# content-eval hit this on their side: comparing schedule values with int() makes int(0.5) ==
# int(0), so a patient who repeats "one tablet" for a prescribed half scores as a MATCH — the
# double-dose miss teach-back exists to catch. These prove the console compares as numbers.


def half_line(**overrides):
    fields = dict(
        id="rx_1",
        schedule=Schedule(morning=0.5, afternoon=0, night=0),
        food_relation="before_food",
        duration_days=60,
        confirmed=True,
    )
    fields.update(overrides)
    return make_line(**fields)


def test_a_whole_tablet_repeated_for_a_prescribed_half_is_a_mismatch():
    result = teachback.compare([half_line()], patient_said={"morning": 1, "duration_days": 60})

    assert result.overall == "mismatch"
    assert "rx_1.morning" in result.mismatched_fields
    assert result.simplest_restatement


def test_a_half_repeated_for_a_prescribed_whole_is_a_mismatch():
    whole = make_line(schedule=Schedule(morning=1, afternoon=0, night=0), duration_days=5,
                      confirmed=True)
    result = teachback.compare([whole], patient_said={"morning": 0.5, "duration_days": 5})

    assert result.overall == "mismatch"
    assert "rx_1.morning" in result.mismatched_fields


def test_a_correctly_repeated_half_is_a_match():
    result = teachback.compare(
        [half_line()], patient_said={"morning": 0.5, "duration_days": 60,
                                     "food_relation": "before_food"}
    )
    assert result.overall == "match"
    assert result.mismatched_fields == []


def test_half_is_extracted_from_english_as_zero_point_five_not_zero():
    """"half" must not parse as 0 — that is the hole that makes a double dose look correct."""
    said = teachback.extract_patient_said("half a tablet in the morning, before food, for 60 days")
    assert said["schedule"] == {"morning": 0.5}

    result = teachback.compare([half_line()], english_text="half a tablet in the morning before food for 60 days")
    assert result.overall == "match"

    wrong = teachback.compare([half_line()], english_text="one tablet in the morning before food for 60 days")
    assert wrong.overall == "mismatch"
    assert "rx_1.morning" in wrong.mismatched_fields


@pytest.mark.parametrize(
    "said,expected",
    [
        ("half a tablet in the morning", 0.5),
        ("one and a half tablets in the morning", 1.5),
        ("two and a half in the morning", 2.5),
        ("0.5 in the morning", 0.5),
        ("1.5 in the morning", 1.5),
        ("one in the morning", 1),
    ],
)
def test_spoken_half_doses_parse_to_numbers(said, expected):
    extracted = teachback.extract_patient_said(said)
    assert extracted["schedule"]["morning"] == expected
