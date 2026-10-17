"""Bad doses are rejected at the type boundary — docs/02 §10.

The console's RxLine is the same type system as the agent's (see test_contract.py), so these are
the values a model cannot get into state on either side.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import RxLine, Schedule

BAD = [
    {"duration_days": 0},
    {"duration_days": 181},
    {"duration_days": 500},
    {"duration_days": "five"},
    {"duration_days": 5.5},
    {"strength_value": -1},
    {"strength_value": 5001},
    {"strength_value": "one-ish spoonful"},
    {"strength_unit": "spoonful"},
    {"form": "lozenge"},
    {"food_relation": "sometimes"},
    {"schedule": {"morning": 5, "afternoon": 0, "night": 0}},
    {"schedule": {"morning": -1, "afternoon": 0, "night": 0}},
    {"schedule": {"morning": "one-ish", "afternoon": 0, "night": 0}},
    {"schedule": {"morning": 1, "afternoon": 0, "night": 0, "bedtime": 1}},
    {"confidence": 1.5},
    {"not_a_field": True},
]


@pytest.mark.parametrize("payload", BAD, ids=lambda p: str(p))
def test_a_hallucinated_dose_cannot_enter_state(payload):
    with pytest.raises(ValidationError):
        RxLine(drug_text="Paracetamol", **payload)


def test_the_legal_edges_are_accepted():
    RxLine(drug_text="X", duration_days=1)
    RxLine(drug_text="X", duration_days=180)
    RxLine(drug_text="X", strength_value=0)
    RxLine(drug_text="X", strength_value=5000)
    RxLine(drug_text="X", schedule=Schedule(morning=4, afternoon=4, night=4))


def test_drug_text_is_required_and_kept_verbatim():
    with pytest.raises(ValidationError):
        RxLine()  # type: ignore[call-arg]
    assert RxLine(drug_text="  Dolo 650 ").drug_text == "  Dolo 650 "
