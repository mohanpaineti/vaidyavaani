"""VaidyaVaani declared state — the dose type system.

This is the single most load-bearing piece of safety in the build.

unmute validates every task `assign:` against the destination field's type here
*before* anything is saved, and an invalid value leaves the task open so the
model corrects itself. So every bound below is a dose the model cannot invent:
`morning: le=4` rejects "ten tablets in the morning", `duration_days: le=180`
rejects "five hundred days", and `food_relation` is an enum rather than free
text. A hallucinated "one-ish spoonful" cannot enter state at all — the agent
asks again instead of proceeding with garbage.

Field names and constraints are fixed by docs/04-interfaces.md §2 and §6.
`console/tests/test_contract.py` imports this module and compares field names
and constraints against the JSON shapes, so a rename here breaks that test.
Do not rename, widen or reorder a field without changing docs/04 first.
"""

from typing import Literal

from pydantic import BaseModel, Field


# How many units at each time of day: a multiple of 0.5, from 0 to 4 inclusive.
#
# `multiple_of` is what makes this a quantised check rather than a bare float.
# It is the whole point of the type: 1, 0.5 and 1.5 are real doses, and 0.25,
# 1.3 and 0.6666 are not. Verified against pydantic — each of those is rejected
# with a `multiple_of` error, as is 1.0000001, while 1, "1" and "0.5" are
# accepted and coerced.
#
# Was `int` until 2026-10-17 (docs/04 §2 records the ruling). "Half a tablet
# twice a day" is one of the commonest dosing forms in Indian practice and is
# in the brief's own edge-case table; under an int schedule it either got
# rejected — which, because an invalid assign leaves the task open, made the
# agent ask again in the middle of a two-minute consultation — or rode in
# `notes` where nothing checks it.
HALF_STEP = 0.5
MAX_UNITS_PER_DOSE = 4


class Schedule(BaseModel):
    """How many units at each time of day. Halves allowed, nothing finer."""

    morning: float = Field(0, ge=0, le=MAX_UNITS_PER_DOSE, multiple_of=HALF_STEP)
    afternoon: float = Field(0, ge=0, le=MAX_UNITS_PER_DOSE, multiple_of=HALF_STEP)
    night: float = Field(0, ge=0, le=MAX_UNITS_PER_DOSE, multiple_of=HALF_STEP)


class RxLine(BaseModel):
    """One prescribed medicine, as structured fields rather than prose.

    `id`, `confidence` and `confirmed` are owned by the Clinic Console, not by
    the agent: they are declared here only so this model matches the `RxLine`
    JSON shape in docs/04 §2 field for field. The agent leaves them at their
    defaults; the console assigns `id`, scores `confidence`, and sets
    `confirmed` when the doctor taps.
    """

    id: str | None = None
    drug_text: str = Field(
        ...,
        description="Exactly as the doctor said it. Never corrected, normalised or expanded.",
    )
    strength_value: float | None = Field(None, ge=0, le=5000)
    strength_unit: Literal["mg", "ml", "g", "iu", "drops"] | None = None
    form: Literal["tablet", "capsule", "syrup", "injection", "drops", "ointment"] | None = None
    schedule: Schedule = Field(default_factory=Schedule)
    food_relation: Literal["before_food", "after_food", "with_food"] | None = None
    duration_days: int | None = Field(None, ge=1, le=180)
    notes: str | None = None
    confidence: float | None = Field(None, ge=0, le=1)
    confirmed: bool = False


class TeachBack(BaseModel):
    """Result of comparing what the patient said back against the confirmed lines.

    Every verdict is computed in Python by the console (docs/04 §2). A model
    only supplies what the patient said; it never decides `overall`.
    """

    overall: Literal["match", "mismatch", "not_attempted"] = "not_attempted"
    mismatched_fields: list[str] = Field(default_factory=list)


class State(BaseModel):
    session_id: str = Field(
        "",
        description="Clinic Console session id. Created by the console and passed in at call start.",
    )
    patient_language: Literal["ta", "kn", "hi", "unsupported", ""] = Field(
        "",
        description=(
            "The patient's language, as a two-letter code: ta for Tamil, kn for Kannada, "
            "hi for Hindi. Use unsupported when the patient speaks a language this "
            "assistant does not cover."
        ),
    )
    consent_given: bool = False
    prescription: list[RxLine] = Field(default_factory=list)
    prescription_confirmed: bool = False
    readback_text: str = Field(
        "",
        description="Rendered by the console from the confirmed fields. Never written by a model.",
    )
    teachback: TeachBack = Field(default_factory=TeachBack)
    voice_note_token: str = ""
