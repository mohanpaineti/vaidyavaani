"""The dose's last mile.

The spoken read-back sentence is rendered here, in Python, by slot-filling the per-language
templates in `content/readback/{ta,kn,hi}.yaml`. The render contract is the comment block at the
top of `content/readback/ta.yaml` and is identical for all three languages; this module implements
exactly that, lifted from content-eval's `eval/readback_render.py` reference.

The two copies stay separate on purpose: `eval/score.py` diffs the **spoken** text against an
independently derived expected string, so if the console produced both sides it would be grading
itself. Any behaviour change here is a change to the contract, not a local decision.

Hard rules, enforced below and proved in tests/test_gate.py and tests/test_readback_templates.py:

* The only inputs are the numbers and enums of a confirmed `RxLine`:
  `schedule`, `form`, `food_relation`, `duration_days`, plus the verbatim `notes` and (for a
  multi-drug prescription only) `drug_text`.
* A line that is not `confirmed` cannot be rendered at all.
* Nothing from a transcript, a model, a tool body or a WS frame is an input. `drug_text` and
  `notes` are fields of the prescription the doctor read on screen and tapped; they are never
  normalised or translated, and braces and newlines are stripped so neither can carry sentence
  structure into the output.
* A line with 0 in every slot RAISES. The patient hears nothing; the doctor gets
  `errors.all_zero_schedule` in English.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import RxLine

log = logging.getLogger("console.readback")

READBACK_LANGUAGES = ("ta", "kn", "hi")

SLOTS = ("morning", "afternoon", "night")

# docs/04 §2: multiples of 0.5 from 0 to 4. 0 is silent, so 0.5–4 need words.
LEGAL_DOSES = tuple(step / 2 for step in range(1, 9))

FORM_KEYS = ("tablet", "capsule", "syrup", "injection", "drops", "ointment", "null_form")

# Keys a language file must provide, as the render contract in content/readback/ta.yaml lists
# them. `examples` and `review` are checked separately — they are content, not render inputs.
REQUIRED_KEYS = (
    "templates",
    "joiners",
    "punctuation",
    "time_of_day",
    "food_relation",
    "count_words",
    "form_nouns",
    "verb_phrase",
    "duration",
    "notes_prefix",
    "errors",
)
REQUIRED_TEMPLATES = ("dose_clause_first", "dose_clause_next", "dose_clause_first_no_food")
REQUIRED_ERRORS = ("all_zero_schedule", "unknown_form", "duration_out_of_range")

# Our own layer, not part of the per-line contract: how several confirmed lines are joined, and
# how each one is named when there is more than one. A single-line read-back names no drug, like
# the brief's model sentence and like every `examples:` case. Set `multi_line_prefix: ""` in a
# content file to turn the naming off.
DEFAULT_LINE_JOIN = " "
DEFAULT_MULTI_LINE_PREFIX = "{drug_text}: "

_TEXT_MAX = 240


class ReadbackError(RuntimeError):
    """A line must not be spoken, or a content file is missing or malformed.

    The message is doctor-facing English. The patient hears nothing.
    """


@dataclass(frozen=True)
class ReadbackTemplate:
    language: str
    data: dict[str, Any]

    @property
    def review_status(self) -> str:
        review = self.data.get("review") or {}
        return str(review.get("status", "unknown"))

    @property
    def examples(self) -> list[dict[str, Any]]:
        return list(self.data.get("examples") or [])


def _verbatim(text: str) -> str:
    """Keep the wording exactly; drop only what could carry structure into the sentence."""
    cleaned = re.sub(r"[{}\r\n\t]+", " ", text or "")
    return re.sub(r"\s+", " ", cleaned).strip()[:_TEXT_MAX]


def load_template(language: str, content_dir: Path) -> ReadbackTemplate:
    if language not in READBACK_LANGUAGES:
        raise ReadbackError(
            f"no read-back template for language {language!r}; have {READBACK_LANGUAGES}"
        )
    path = Path(content_dir) / "readback" / f"{language}.yaml"
    if not path.exists():
        raise ReadbackError(
            f"read-back template not found: {path}. content/ is owned by the content-eval "
            f"session; set CONSOLE_CONTENT_DIR to point at it."
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ReadbackError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ReadbackError(f"{path} must be a YAML mapping, got {type(data).__name__}")

    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        raise ReadbackError(f"{path} is missing required key(s): {', '.join(missing)}")
    for key in REQUIRED_TEMPLATES:
        if key not in data["templates"]:
            raise ReadbackError(f"{path}: templates is missing {key!r}")
    for key in REQUIRED_ERRORS:
        if key not in data["errors"]:
            raise ReadbackError(f"{path}: errors is missing {key!r}")
    for slot in SLOTS:
        if slot not in data["time_of_day"]:
            raise ReadbackError(f"{path}: time_of_day is missing {slot!r}")
    for relation in ("before_food", "after_food", "with_food"):
        if relation not in data["food_relation"]:
            raise ReadbackError(f"{path}: food_relation is missing {relation!r}")
    # docs/04 §2 (changed 2026-10-17): a schedule slot is any multiple of 0.5 in 0–4, so every
    # one of those values needs its own word. Tamil and Kannada fuse the half into one word
    # (ஒன்றரை, ಒಂದೂವರೆ) and Hindi is suppletive (डेढ़, ಢाई, साढ़े तीन), so none of them can be
    # composed from "one" and "half" — they are looked up, by value.
    table = _count_table(data, path)
    missing = [value for value in LEGAL_DOSES if value not in table]
    if missing:
        # A warning, not a refusal: a file that covers the doses actually prescribed is usable,
        # and `render_line` blocks the specific dose it cannot say. Startup should not fail
        # because one rare count has no word yet.
        log.warning(
            "%s: count_words has no word for %s. A line prescribing one of those doses will be "
            "blocked at the gate rather than spoken.",
            path,
            ", ".join(_show_dose(value) for value in missing),
        )
    for key in FORM_KEYS:
        if key not in data["form_nouns"]:
            raise ReadbackError(f"{path}: form_nouns is missing {key!r}")
        if key not in data["verb_phrase"]:
            raise ReadbackError(f"{path}: verb_phrase is missing {key!r}")
    duration = data["duration"]
    for key in ("template", "one_day", "day_words"):
        if key not in duration:
            raise ReadbackError(f"{path}: duration is missing {key!r}")

    template = ReadbackTemplate(language=language, data=data)
    if template.review_status != "signed_off":
        log.warning(
            "readback/%s.yaml is still NEEDS-NATIVE-REVIEW (review.status=%s). The rendered "
            "sentence is a draft; `python eval/score.py review-status` counts what is left.",
            language,
            template.review_status,
        )
    return template


def _form_entry(data: dict[str, Any], form: str | None) -> tuple[str, str | None]:
    """(noun, gender). Hindi carries a gender the verb and 'half' agree with; ta/kn do not."""
    key = form if form is not None else "null_form"
    nouns = data["form_nouns"]
    if key not in nouns:
        raise ReadbackError(data["errors"]["unknown_form"])
    entry = nouns[key]
    if isinstance(entry, dict):
        if "word" not in entry:
            raise ReadbackError(f"form_nouns.{key} is a mapping without a 'word'")
        return entry["word"], entry.get("gender")
    return entry, None


def _show_dose(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _count_table(data: dict[str, Any], path: Any = "readback") -> dict[float, Any]:
    """`count_words` keyed by value.

    YAML hands back a mix of int and float keys (`1`, `0.5`), and older files used the literal
    key `half`. Normalising to float means a schedule value of 1, 1.0 or 1.00 all find the same
    word, and a lookup is never a string formatting of the number.
    """
    table: dict[float, Any] = {}
    for key, word in (data.get("count_words") or {}).items():
        if key == "half":
            table[0.5] = word
            continue
        try:
            table[float(key)] = word
        except (TypeError, ValueError):
            raise ReadbackError(
                f"{path}: count_words key {key!r} is not a dose value"
            ) from None
    return table


def _count_word(data: dict[str, Any], count: int | float, gender: str | None) -> str:
    """Looked up by value — never str(n), and never composed from smaller words.

    Tamil's ஒரு is the only form allowed before a noun, Tamil and Kannada fuse a half into one
    word, and Hindi's 1.5/2.5 are suppletive. Every one of those is a lookup.
    """
    word = _count_table(data).get(float(count))
    if word is None:
        raise ReadbackError(
            f"Read-back blocked: no word for a dose of {_show_dose(count)}. content/readback/ "
            f"needs a count_words entry for {_show_dose(count)} — composing one from smaller "
            f"words would invent grammar. Until then, express this dose through two slots or "
            f"the notes field."
        )
    if isinstance(word, dict):  # the gendered shape Hindi's 0.5 uses
        if gender is None or gender not in word:
            raise ReadbackError(
                f"count_words[{_show_dose(count)}] needs a gender and got {gender!r}"
            )
        return word[gender]
    return word


def _duration_phrase(data: dict[str, Any], days: int) -> str:
    duration = data["duration"]
    if days == 1:
        return duration["one_day"]
    word = duration["day_words"].get(days)
    if word is None:
        # Documented fallback: speak the digits rather than risk a wrong number word.
        if not duration.get("digit_fallback", False):
            raise ReadbackError(f"no word for {days} days and digit_fallback is off")
        word = str(days)
    return duration["template"].replace("{days}", word)


def render_line(line: RxLine, template: ReadbackTemplate) -> str:
    """Render one confirmed RxLine into the sentence the patient will hear.

    Follows the render contract at the top of content/readback/ta.yaml step for step.
    """
    if not line.confirmed:
        raise ReadbackError(
            f"refusing to render read-back for unconfirmed line {line.id or '<new>'}"
        )

    data = template.data
    for slot in SLOTS:
        count = getattr(line.schedule, slot)
        if isinstance(count, bool) or not isinstance(count, (int, float)):
            raise ReadbackError(f"schedule.{slot} must be a number, got {count!r}")
        if not 0 <= count <= 4 or (count * 2) % 1 != 0:
            raise ReadbackError(
                f"schedule.{slot} must be a multiple of 0.5 in 0-4 (docs/04 §2), got {count!r}"
            )
    if line.duration_days is not None and not 1 <= line.duration_days <= 180:
        raise ReadbackError(data["errors"]["duration_out_of_range"])

    noun, gender = _form_entry(data, line.form)

    clauses: list[str] = []
    for slot in SLOTS:
        count = getattr(line.schedule, slot)
        if count == 0:
            continue  # a 0 slot is SILENT — never "zero in the morning"
        count_word = _count_word(data, count, gender)
        if not clauses:
            # food relation and the form noun appear on the FIRST clause only
            key = "dose_clause_first" if line.food_relation is not None else "dose_clause_first_no_food"
            clause = data["templates"][key]
            clause = clause.replace("{time_of_day}", data["time_of_day"][slot])
            if line.food_relation is not None:
                clause = clause.replace(
                    "{food_relation}", data["food_relation"][line.food_relation]
                )
            clause = clause.replace("{count}", count_word).replace("{form}", noun)
        else:
            clause = data["templates"]["dose_clause_next"]
            clause = clause.replace("{time_of_day}", data["time_of_day"][slot])
            clause = clause.replace("{count}", count_word)
        clauses.append(" ".join(clause.split()))

    if not clauses:
        # Every slot is 0. Nothing is spoken; the doctor is told why, in English.
        raise ReadbackError(data["errors"]["all_zero_schedule"])

    sentence = data["joiners"]["clause"].join(clauses)
    if line.duration_days is not None:
        sentence += data["joiners"]["clause"] + _duration_phrase(data, line.duration_days)

    verb_key = line.form if line.form is not None else "null_form"
    sentence += data["joiners"]["before_verb"] + data["verb_phrase"][verb_key]
    sentence += data["punctuation"]["end"]

    if line.notes:
        # Verbatim, as the doctor confirmed it (docs/01 §4 — `notes`: read back verbatim).
        sentence += " " + data["notes_prefix"] + _verbatim(line.notes) + data["punctuation"]["end"]
    return sentence


def render(lines: list[RxLine], language: str, content_dir: Path) -> str:
    """Render the whole confirmed prescription into the sentence the patient will hear.

    Per-line rendering is the contract. Joining several lines is this console's layer: the
    sentences are joined with `joiners.line`, and when there is more than one line each is named
    with its `drug_text` via `templates.multi_line_prefix` so the patient can tell two medicines
    apart. A single-line read-back names no drug, exactly like the `examples:` cases.
    """
    confirmed = [ln for ln in lines if ln.confirmed]
    if not lines or len(confirmed) != len(lines):
        raise ReadbackError(
            "read-back is rendered only from a fully confirmed prescription "
            f"({len(confirmed)}/{len(lines)} lines confirmed)"
        )
    template = load_template(language, content_dir)
    joiners = template.data["joiners"]
    line_join = joiners.get("line", DEFAULT_LINE_JOIN)
    # content/readback/*.yaml carries this at the top level; the templates block is accepted too.
    prefix_template = template.data.get(
        "multi_line_prefix",
        template.data["templates"].get("multi_line_prefix", DEFAULT_MULTI_LINE_PREFIX),
    )

    sentences: list[str] = []
    for line in lines:
        sentence = render_line(line, template)
        if len(lines) > 1 and prefix_template:
            sentence = (
                prefix_template.replace("{drug_text}", _verbatim(line.drug_text)) + sentence
            )
        sentences.append(sentence)
    return unicodedata.normalize("NFC", line_join.join(sentences)).strip()


def normalise(text: str) -> str:
    """NFC + whitespace collapse, for comparing a rendered string against a template's example."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def review_status(content_dir: Path) -> dict[str, str]:
    """Per-language `review.status`, for /healthz. 'pending' means the strings are drafts."""
    statuses: dict[str, str] = {}
    for language in READBACK_LANGUAGES:
        try:
            statuses[language] = load_template(language, content_dir).review_status
        except ReadbackError:
            statuses[language] = "missing"
    return statuses
