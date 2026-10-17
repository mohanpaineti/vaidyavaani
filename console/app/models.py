"""The shapes from docs/04 §2. Field names are exact — nothing is renamed at the edges."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from types import UnionType
from typing import Union, get_args, get_origin

from annotated_types import Ge, Le, MultipleOf
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

StrengthUnit = Literal["mg", "ml", "g", "iu", "drops"]
Form = Literal["tablet", "capsule", "syrup", "injection", "drops", "ointment"]
FoodRelation = Literal["before_food", "after_food", "with_food"]
PatientLanguage = Literal["ta", "kn", "hi", "unsupported", ""]
Side = Literal["patient", "doctor", "agent"]
Stage = Literal[
    "start",
    "consent",
    "interpret",
    "prescribe",
    "await_confirm",
    "readback",
    "teachback",
    "takehome",
    "ended",
]
Verdict = Literal["match", "mismatch", "not_mentioned"]


def _not_a_bool(value: Any) -> Any:
    """`True` would otherwise coerce to a dose of 1. A boolean dose is nonsense."""
    if isinstance(value, bool):
        raise ValueError("a schedule slot must be a number, not a boolean")
    return value


def _whole_doses_stay_int(value: int | float) -> int | float:
    """A whole dose leaves the console as `1`, never `1.0`.

    The agent's `state.py` types these as `float`, so a line arriving from a tool call carries
    `1.0`. docs/04 §2 shows integers, and a card reading "1.0 tablet" is worse than one reading
    "1", so the console normalises on the way in. 0.5 stays 0.5.
    """
    return int(value) if float(value).is_integer() else float(value)


# docs/04 §2: numbers in multiples of 0.5 from 0 to 4 inclusive. 1, 0.5 and 1.5 are legal;
# 0.25 and 1.3 are rejected at the type boundary. `int | float` keeps a whole dose an int, so
# the JSON stays `1` rather than `1.0`.
DoseCount = Annotated[
    int | float,
    BeforeValidator(_not_a_bool),
    Ge(0),
    Le(4),
    MultipleOf(0.5),
    AfterValidator(_whole_doses_stay_int),
]


class BlankAsAbsent(BaseModel):
    """Treats an empty string as an absent value on every nullable field.

    unmute builds every tool call **by keyword, every time**, so an optional tool input is always
    supplied — as `""` when the model omits it (docs/04 §3). Without this, `notes` would arrive
    `""` instead of `null` and an omitted optional enum would arrive `""` and fail validation.
    The coercion happens here, at the point of entry, so nothing downstream carries empty strings
    where the contract says null.
    """

    @classmethod
    def _nullable_fields(cls) -> frozenset[str]:
        cached = cls.__dict__.get("_nullable_field_names")
        if cached is None:
            names = set()
            for name, field in cls.model_fields.items():
                annotation = field.annotation
                if get_origin(annotation) in (Union, UnionType) and type(None) in get_args(
                    annotation
                ):
                    names.add(name)
            cached = frozenset(names)
            setattr(cls, "_nullable_field_names", cached)
        return cached

    @model_validator(mode="before")
    @classmethod
    def _blank_to_none(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        nullable = cls._nullable_fields()
        cleaned = {
            key: (None if key in nullable and value == "" else value)
            for key, value in data.items()
        }
        return cleaned


def now_iso() -> str:
    """UTC, second resolution, trailing Z — the format in every example in docs/04."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Schedule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    morning: DoseCount = 0
    afternoon: DoseCount = 0
    night: DoseCount = 0


class RxLine(BlankAsAbsent):
    """One prescribed medicine. `drug_text` is never normalised, corrected or expanded."""

    model_config = ConfigDict(extra="forbid")

    # docs/04 §2: `string | null` — minted by the console, so it is absent on a line the agent
    # produces and present on every line the console emits (asserted in tests/test_contract.py).
    id: str | None = None
    drug_text: str
    strength_value: float | None = Field(None, ge=0, le=5000)
    strength_unit: StrengthUnit | None = None
    form: Form | None = None
    schedule: Schedule = Field(default_factory=Schedule)
    food_relation: FoodRelation | None = None
    duration_days: int | None = Field(None, ge=1, le=180)
    notes: str | None = None
    confidence: float | None = Field(None, ge=0, le=1)
    confirmed: bool = False


class LayTerm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    said: str
    likely_means: str


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    side: Side
    original_text: str = ""
    english_text: str = ""
    detected_language: str = ""
    lay_terms: list[LayTerm] = Field(default_factory=list)
    negations: list[str] = Field(default_factory=list)
    at: str = Field(default_factory=now_iso)


class RedFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    phrase: str
    english: str
    source: Literal["keyword", "llm"]
    severity: Literal["watch", "urgent"]
    at: str = Field(default_factory=now_iso)
    acknowledged: bool = False


class TeachBackLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_id: str
    morning: Verdict
    afternoon: Verdict
    night: Verdict
    duration: Verdict
    food_relation: Verdict
    patient_said: dict[str, Any] = Field(default_factory=dict)


class TeachBackResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall: Literal["match", "mismatch", "not_attempted"]
    per_line: list[TeachBackLine] = Field(default_factory=list)
    mismatched_fields: list[str] = Field(default_factory=list)
    simplest_restatement: str = ""


class Consent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    given: bool = False
    at: str | None = None


class Prescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[RxLine] = Field(default_factory=list)
    all_confirmed: bool = False
    confirmed_at: str | None = None


class VoiceNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str
    url: str
    qr_data_uri: str
    language: str = ""
    expires_at: str = ""


class Metrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turns: int = 0
    reply_latency_p90_ms: float | None = None
    last_reply_latency_ms: float | None = None


class SessionState(BaseModel):
    """Exactly what the UI renders (docs/04 §2)."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    patient_language: PatientLanguage = ""
    doctor_language: str = "en"
    consent: Consent = Field(default_factory=Consent)
    stage: Stage = "start"
    turns: list[Turn] = Field(default_factory=list)
    red_flags: list[RedFlag] = Field(default_factory=list)
    prescription: Prescription = Field(default_factory=Prescription)
    teachback: TeachBackResult | None = None
    voice_note: VoiceNote | None = None
    metrics: Metrics = Field(default_factory=Metrics)
