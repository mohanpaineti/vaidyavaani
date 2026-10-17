"""Reference implementation of the read-back render.

The console owns the real one (console/app/readback.py, per docs/04 §0). This
is a SECOND, independent implementation living in eval/, for two reasons:

1. `eval/score.py verbatim` needs an expected string to diff the SPOKEN text
   against. Taking it from the console would mean the console grading itself.
2. It is an executable spec of the render contract written at the top of
   content/readback/ta.yaml. If console-backend's output and this disagree,
   one of us has misread the contract and we want to know before demo day.

Inputs are ONLY the integers and enums of a confirmed RxLine (docs/04 §2).
No model, no transcript text, no network.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "PyYAML is required: pip install -r eval/requirements.txt"
    ) from exc

CONTENT = Path(__file__).resolve().parent.parent / "content" / "readback"
SLOTS = ("morning", "afternoon", "night")


class ReadbackError(ValueError):
    """Raised when a line must NOT be spoken. The doctor sees this, not the patient."""


_cache: dict[str, dict] = {}


def load(lang: str) -> dict:
    if lang not in _cache:
        path = CONTENT / f"{lang}.yaml"
        if not path.exists():
            raise ReadbackError(f"no read-back template for language {lang!r}")
        _cache[lang] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _cache[lang]


def _count_table(tpl: dict) -> dict[float, object]:
    """YAML gives us a mix of int and float keys (1, 0.5). Normalise to float
    so a schedule value of 1, 1.0 or 1.00 all find the same word."""
    return {float(k): v for k, v in tpl["count_words"].items()}


def _check_count(value) -> float:
    """schedule values are multiples of 0.5 in 0-4 (docs/04 §2, changed
    2026-10-17 from int). 0.25 and 1.3 are rejected at this boundary."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReadbackError(f"schedule value must be a number, got {value!r}")
    v = float(value)
    if not 0 <= v <= 4:
        raise ReadbackError(f"schedule value {value!r} is outside 0-4")
    if abs(v * 2 - round(v * 2)) > 1e-9:
        raise ReadbackError(
            f"schedule value {value!r} is not a multiple of 0.5 (docs/04 §2)"
        )
    return v


def _form_entry(tpl: dict, form: str | None) -> tuple[str, str | None]:
    """Return (noun, gender). Hindi carries gender; Tamil and Kannada do not."""
    key = form if form is not None else "null_form"
    nouns = tpl["form_nouns"]
    if key not in nouns:
        raise ReadbackError(tpl["errors"]["unknown_form"])
    entry = nouns[key]
    if isinstance(entry, dict):
        return entry["word"], entry.get("gender")
    return entry, None


def _duration_phrase(tpl: dict, days: int) -> str:
    dur = tpl["duration"]
    if days == 1:
        return dur["one_day"]
    word = dur["day_words"].get(days)
    if word is None:
        # Documented fallback: speak the digits rather than risk a wrong number word.
        if not dur.get("digit_fallback", False):
            raise ReadbackError(f"no word for {days} days and digit_fallback is off")
        word = str(days)
    return dur["template"].replace("{days}", word)


def render(line: dict, lang: str) -> str:
    """Render one confirmed RxLine into the sentence the patient will hear."""
    tpl = load(lang)
    schedule = line["schedule"]
    form = line.get("form")
    food = line.get("food_relation")
    days = line.get("duration_days")

    counts = {}
    for slot in SLOTS:
        try:
            counts[slot] = _check_count(schedule[slot])
        except ReadbackError as exc:
            raise ReadbackError(f"schedule.{slot}: {exc}") from None
    if days is not None and not 1 <= days <= 180:
        raise ReadbackError(tpl["errors"]["duration_out_of_range"])

    noun, gender = _form_entry(tpl, form)
    table = _count_table(tpl)
    clauses: list[str] = []
    for slot in SLOTS:
        n = counts[slot]
        if n == 0:
            continue  # a 0 slot is SILENT — never "zero in the morning"
        if n not in table:
            raise ReadbackError(
                f"no count word for {n} in content/readback/{lang}.yaml"
            )
        count = table[n]
        if isinstance(count, dict):
            # Hindi: only 0.5 is gendered (आधी/आधा). डेढ़, ढाई and साढ़े तीन are
            # suppletive forms that do not agree with anything.
            count = count[gender]
        if not clauses:
            key = (
                "dose_clause_first" if food is not None else "dose_clause_first_no_food"
            )
            clause = tpl["templates"][key]
            clause = clause.replace("{time_of_day}", tpl["time_of_day"][slot])
            if food is not None:
                clause = clause.replace("{food_relation}", tpl["food_relation"][food])
            clause = clause.replace("{count}", count).replace("{form}", noun)
        else:
            clause = tpl["templates"]["dose_clause_next"]
            clause = clause.replace("{time_of_day}", tpl["time_of_day"][slot])
            clause = clause.replace("{count}", count)
        clauses.append(" ".join(clause.split()))

    if not clauses:
        # Every slot is 0. Nothing is spoken; the doctor is told why.
        raise ReadbackError(tpl["errors"]["all_zero_schedule"])

    sentence = tpl["joiners"]["clause"].join(clauses)
    if days is not None:
        sentence += tpl["joiners"]["clause"] + _duration_phrase(tpl, days)

    verb_key = form if form is not None else "null_form"
    sentence += tpl["joiners"]["before_verb"] + tpl["verb_phrase"][verb_key]
    sentence += tpl["punctuation"]["end"]

    notes = line.get("notes")
    if notes:
        # Verbatim, as the doctor confirmed it (docs/01 §4).
        sentence += " " + tpl["notes_prefix"] + notes + tpl["punctuation"]["end"]
    return sentence


def normalise(text: str) -> str:
    """NFC + whitespace collapse. Used for the lenient half of the verbatim check."""
    return " ".join(unicodedata.normalize("NFC", text).split())


# --- whole-prescription render ------------------------------------------
#
# Per-line rendering above is the contract written at the top of
# content/readback/ta.yaml. Joining several confirmed lines into the ONE string
# the gate returns is the console's layer (console/app/readback.py:render), and
# eval has to mirror it or it diffs the wrong unit: the gate hands the agent a
# single `readback_text` for the whole prescription, so a two-line prescription
# is ONE spoken utterance, not two. Scoring it line by line reports a deviation
# on every multi-line row and finds nothing real.

DEFAULT_LINE_JOIN = " "


def render_prescription(lines: list[dict], lang: str) -> str:
    """Render every confirmed line into the single sentence the gate returns."""
    if not lines:
        raise ReadbackError("no confirmed lines to read back")
    tpl = load(lang)
    join = tpl["joiners"].get("line", DEFAULT_LINE_JOIN)
    prefix = tpl.get("multi_line_prefix", tpl["templates"].get("multi_line_prefix", ""))
    sentences = []
    for line in lines:
        sentence = render(line, lang)
        if len(lines) > 1 and prefix:
            # drug_text is inserted exactly as the doctor confirmed it — never
            # translated, transliterated or normalised (docs/04 §2).
            sentence = prefix.replace("{drug_text}", line["drug_text"]) + sentence
        sentences.append(sentence)
    return join.join(sentences)
