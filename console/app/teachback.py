"""Teach-back comparison.

The patient repeats the instructions back; we check whether what they said matches the dose the
doctor confirmed. **Every verdict in the returned TeachBackResult is computed here, in Python.**
A model supplies only `patient_said` — and when it supplies nothing, we extract the numbers
ourselves with a deterministic parser. Numbers are compared arithmetically, never as strings.
"""

from __future__ import annotations

import re
from typing import Any

from .models import RxLine, TeachBackLine, TeachBackResult

NUMBER_WORDS: dict[str, int | float] = {
    "zero": 0, "none": 0, "no": 0,
    # docs/04 §2 (changed 2026-10-17): doses are multiples of 0.5, so "half" is 0.5 — NOT 0.
    # Mapping it to 0 would score a patient who repeats "one tablet" for a prescribed half as a
    # match, which is the double-dose miss teach-back exists to catch.
    "half": 0.5,
    "one": 1, "a": 1, "an": 1,
    "two": 2, "twice": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fourteen": 14,
    "fifteen": 15, "twenty": 20, "thirty": 30,
}

# Spoken half-doses, normalised to digits before anything is parsed. Longest first: "one and a
# half" must win over the bare "half" inside it.
HALF_PHRASES: list[tuple[str, str]] = [
    (r"\b(?:three|3)\s+and\s+(?:a\s+)?half\b", "3.5"),
    (r"\b(?:two|2)\s+and\s+(?:a\s+)?half\b", "2.5"),
    (r"\b(?:one|1|a|an)\s+and\s+(?:a\s+)?half\b", "1.5"),
    (r"\bone\s+point\s+five\b", "1.5"),
    (r"\bhalf\s+(?:a|an|one)\b", "0.5"),
    (r"\ba\s+half\b", "0.5"),
    (r"\bhalf\b", "0.5"),
]

TIME_WORDS = {
    "morning": "morning",
    "mornings": "morning",
    "breakfast": "morning",
    "afternoon": "afternoon",
    "afternoons": "afternoon",
    "noon": "afternoon",
    "midday": "afternoon",
    "lunch": "afternoon",
    "night": "night",
    "nights": "night",
    "evening": "night",
    "evenings": "night",
    "bedtime": "night",
    "dinner": "night",
}

FOOD_PATTERNS = [
    (r"\bafter\s+(?:food|meals?|eating|lunch|dinner|breakfast)\b", "after_food"),
    (r"\bbefore\s+(?:food|meals?|eating|lunch|dinner|breakfast)\b", "before_food"),
    (r"\bwith\s+(?:food|meals?|water\s+and\s+food)\b", "with_food"),
    (r"\bon\s+an?\s+empty\s+stomach\b", "before_food"),
]

ENGLISH_NUMBER_NAME = {
    1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven",
    8: "Eight", 9: "Nine", 10: "Ten",
}

_SLOTS = ("morning", "afternoon", "night")


def _to_number(token: str) -> int | float | None:
    """A dose or a day count. Returns an int for a whole number so patient_said stays `1`."""
    token = token.strip().lower()
    if token.isdigit():
        return int(token)
    try:
        value = float(token)
    except ValueError:
        return NUMBER_WORDS.get(token)
    return int(value) if value.is_integer() else value


def _normalise(text: str) -> str:
    """Lower-case, strip punctuation, and turn spoken halves into digits.

    The decimal point survives the punctuation strip so "0.5" and "1.5" stay numbers.
    """
    lowered = (text or "").lower()
    for pattern, replacement in HALF_PHRASES:
        lowered = re.sub(pattern, replacement, lowered)
    return re.sub(r"[^\w\s.]", " ", lowered)


def extract_patient_said(english_text: str) -> dict[str, Any]:
    """Pull dose fields out of the English rendering of what the patient said.

    Deterministic and dumb on purpose: regex and integer arithmetic, no model, no fuzzy matching.
    Anything not found is simply absent, which the comparison reports as `not_mentioned`.
    """
    said: dict[str, Any] = {}
    text = _normalise(english_text)

    # duration: "for five days", "5 days", "three more days"
    m = re.search(r"\b(?:for\s+)?([\d.]+|[a-z]+)\s+(?:more\s+)?(?:days?|day)\b", text)
    if m:
        days = _to_number(m.group(1))
        if days is not None:
            said["duration_days"] = days

    # schedule: a count immediately before or after a time-of-day word
    schedule: dict[str, int | float] = {}
    tokens = text.split()
    for i, token in enumerate(tokens):
        slot = TIME_WORDS.get(token)
        if slot is None:
            continue
        count: int | float | None = None
        # look back over a short window: "one tablet in the morning", "2 in the morning"
        for j in range(max(0, i - 4), i):
            value = _to_number(tokens[j])
            if value is not None:
                count = value
        if count is None:
            # look forward: "morning one tablet"
            for j in range(i + 1, min(len(tokens), i + 4)):
                value = _to_number(tokens[j])
                if value is not None:
                    count = value
                    break
        if count is None:
            count = 1  # "a tablet at night" — mentioned, so assume the single dose they described
        schedule[slot] = count
    # "nothing in the afternoon" / "skip the afternoon"
    for slot in _SLOTS:
        if re.search(rf"\b(?:no|nothing|skip|not)\b[\w\s]{{0,20}}\b{slot}\b", text):
            schedule[slot] = 0
    if schedule:
        said["schedule"] = schedule

    for pattern, value in FOOD_PATTERNS:
        if re.search(pattern, text):
            said["food_relation"] = value
            break

    # twice/three times a day, with no slots named
    m = re.search(r"\b(once|twice|thrice|\d+|[a-z]+)\s+(?:times?\s+)?(?:a|per|each)\s+day\b", text)
    if m and "times_per_day" not in said:
        token = m.group(1)
        value = {"once": 1, "twice": 2, "thrice": 3}.get(token, _to_number(token))
        if value is not None:
            said["times_per_day"] = value

    return said


def _segments_for_lines(lines: list[RxLine], english_text: str) -> dict[str, str]:
    """Attribute parts of the read-back to lines by where each drug name is named.

    One line: the whole text is about it. Several lines: the text is split at each drug name, and
    anything said before the first named drug is attributed to nothing (reported as
    `not_mentioned`) rather than guessed at.
    """
    if len(lines) <= 1:
        return {lines[0].id: english_text} if lines else {}

    haystack = (english_text or "").lower()
    hits: list[tuple[int, str]] = []
    for line in lines:
        name = (line.drug_text or "").strip().lower()
        if not name:
            continue
        pos = haystack.find(name.split()[0])
        if pos >= 0:
            hits.append((pos, line.id))
    hits.sort()
    segments = {line.id: "" for line in lines}
    for idx, (pos, line_id) in enumerate(hits):
        end = hits[idx + 1][0] if idx + 1 < len(hits) else len(english_text or "")
        segments[line_id] = (english_text or "")[pos:end]
    return segments


def _normalise_said(said: dict[str, Any]) -> dict[str, Any]:
    """Accept both `patient_said` shapes: flat slot keys, or nested under `schedule`.

    eval/fixtures/teachback_cases.json uses the flat form
    (`{"morning": 1, "night": 1, "duration_days": 2}`); docs/04 §2's example nests the schedule.
    Both mean the same thing, and neither carries a verdict.
    """
    normalised = {k: v for k, v in said.items() if k not in _SLOTS}
    schedule = dict(said.get("schedule") or {})
    for slot in _SLOTS:
        if slot in said:
            schedule[slot] = said[slot]
    if schedule:
        normalised["schedule"] = schedule
    return normalised


def _verdict(expected: Any, actual: Any) -> str:
    if actual is None:
        return "not_mentioned"
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return "match" if float(expected) == float(actual) else "mismatch"
    return "match" if expected == actual else "mismatch"


def _restatement(lines: list[RxLine], per_line: list[TeachBackLine]) -> str:
    """One short English sentence naming the first thing that was wrong, from confirmed fields."""
    by_id = {ln.id: ln for ln in lines}
    for result in per_line:
        line = by_id[result.line_id]
        said = result.patient_said or {}
        said_schedule = said.get("schedule") or {}
        if result.duration == "mismatch":
            correct = ENGLISH_NUMBER_NAME.get(line.duration_days or 0, str(line.duration_days))
            heard = said.get("duration_days")
            heard_name = ENGLISH_NUMBER_NAME.get(heard, str(heard)).lower()
            return f"{correct} days, not {heard_name} days."
        for slot in _SLOTS:
            if getattr(result, slot) == "mismatch":
                expected = getattr(line.schedule, slot)
                heard = said_schedule.get(slot)
                return (
                    f"{ENGLISH_NUMBER_NAME.get(expected, str(expected))} in the {slot}, "
                    f"not {heard}."
                )
        if result.food_relation == "mismatch":
            want = (line.food_relation or "").replace("_", " ")
            heard = str(said.get("food_relation", "")).replace("_", " ")
            return f"{want.capitalize()}, not {heard}."
    return ""


def compare(
    lines: list[RxLine],
    patient_text: str = "",
    english_text: str = "",
    patient_said: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> TeachBackResult:
    """Compare the patient's read-back against the confirmed prescription.

    `patient_said` is the only thing a model may supply, and only as *values*; if it is absent we
    extract the same values from `english_text` ourselves. Either way the verdicts below are ours.
    """
    if not lines:
        return TeachBackResult(overall="not_attempted")

    supplied: dict[str, dict[str, Any]] = {}
    if isinstance(patient_said, dict):
        keyed_by_line = {
            k: v for k, v in patient_said.items() if isinstance(v, dict) and k.startswith("rx_")
        }
        if keyed_by_line:
            supplied = {k: _normalise_said(v) for k, v in keyed_by_line.items()}
        elif len(lines) == 1:
            supplied = {lines[0].id: _normalise_said(patient_said)}
    elif isinstance(patient_said, list):
        for item in patient_said:
            line_id = item.get("line_id")
            if line_id:
                supplied[line_id] = _normalise_said(
                    {k: v for k, v in item.items() if k != "line_id"}
                )

    segments = _segments_for_lines(lines, english_text or patient_text)

    per_line: list[TeachBackLine] = []
    mismatched: list[str] = []
    saw_any = False

    for line in lines:
        said = supplied.get(line.id)
        if said is None:
            said = extract_patient_said(segments.get(line.id, ""))
        said_schedule = said.get("schedule") or {}
        if said:
            saw_any = True

        verdicts: dict[str, str] = {}
        for slot in _SLOTS:
            expected = getattr(line.schedule, slot)
            actual = said_schedule.get(slot)
            if actual is None and "times_per_day" in said and not said_schedule:
                actual = None  # a bare "twice a day" says nothing about which slots
            if actual is None and expected == 0:
                # nothing claimed for a slot with no dose: not a mismatch, just unsaid
                verdicts[slot] = "not_mentioned"
                continue
            verdicts[slot] = _verdict(expected, actual)

        duration = _verdict(line.duration_days, said.get("duration_days"))
        if line.duration_days is None:
            duration = "not_mentioned" if said.get("duration_days") is None else "mismatch"

        food = _verdict(line.food_relation, said.get("food_relation"))
        if line.food_relation is None:
            food = "not_mentioned" if said.get("food_relation") is None else "mismatch"

        result = TeachBackLine(
            line_id=line.id,
            morning=verdicts["morning"],
            afternoon=verdicts["afternoon"],
            night=verdicts["night"],
            duration=duration,
            food_relation=food,
            patient_said=said,
        )
        per_line.append(result)

        for field in ("morning", "afternoon", "night", "duration", "food_relation"):
            if getattr(result, field) == "mismatch":
                mismatched.append(f"{line.id}.{field}")

    if mismatched:
        overall = "mismatch"
    elif not saw_any:
        overall = "not_attempted"
    else:
        overall = "match"

    return TeachBackResult(
        overall=overall,
        per_line=per_line,
        mismatched_fields=mismatched,
        simplest_restatement=_restatement(lines, per_line) if mismatched else "",
    )
