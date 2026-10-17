"""Read-back templates — the dose's last mile.

The clinical wording belongs to content-eval; what must hold here is that the render follows the
contract at the top of `content/readback/ta.yaml` exactly. The authority for that is each
language file's own `examples:` block — 18 cases across ta/kn/hi, each with the input RxLine and
the exact expected sentence, including one per language that must RAISE.

Those cases run against the fixture snapshot of content-eval commit 6485550 and, when the real
`content/` has landed, against the real files too.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app import config, readback
from app.models import RxLine, Schedule
from tests.conftest import make_line, requires_content

LANGUAGES = readback.READBACK_LANGUAGES
REAL_CONTENT = Path(config.REPO_ROOT) / "content"

pytestmark = requires_content


def _missing_dose_words(language: str) -> list[float]:
    """Legal doses (docs/04 §2) that this language file has no word for."""
    template = readback.load_template(language, REAL_CONTENT)
    table = readback._count_table(template.data)
    return [dose for dose in readback.LEGAL_DOSES if dose not in table]


def _needs_every_dose_word(language: str) -> None:
    """Skip a dependent case when the content is the thing that is missing.

    `test_every_legal_dose_has_a_word` is the one test that reports this, so the suite shows a
    single root cause rather than nine failures with the same reason.
    """
    missing = _missing_dose_words(language)
    if missing:
        pytest.skip(
            f"readback/{language}.yaml has no word for "
            f"{', '.join(readback._show_dose(dose) for dose in missing)} — reported by "
            f"test_every_legal_dose_has_a_word"
        )


def _line_from_example(rx: dict, **overrides) -> RxLine:
    fields = dict(
        id="rx_1",
        drug_text="Paracetamol",
        schedule=Schedule(**rx["schedule"]),
        food_relation=rx.get("food_relation"),
        form=rx.get("form"),
        duration_days=rx.get("duration_days"),
        notes=rx.get("notes"),
        strength_value=rx.get("strength_value"),
        strength_unit=rx.get("strength_unit"),
        confirmed=True,
    )
    fields.update(overrides)
    return RxLine(**fields)


def _examples(content_dir: Path) -> list[tuple[str, dict]]:
    if not (content_dir / "readback" / "ta.yaml").exists():
        return []
    cases = []
    for language in LANGUAGES:
        template = readback.load_template(language, content_dir)
        for example in template.examples:
            cases.append((language, example))
    return cases


# The authority block, read from content/ itself — never from a copy of it.
CONTENT_EXAMPLES = _examples(REAL_CONTENT)


def _run_example(language: str, example: dict, content_dir: Path) -> None:
    template = readback.load_template(language, content_dir)
    line = _line_from_example(example["rx"])
    expected = str(example["expect"])

    if expected.startswith("RAISE"):
        with pytest.raises(readback.ReadbackError) as exc:
            readback.render_line(line, template)
        # the doctor-facing message, in English, from the content file's errors block
        key = expected.split("RAISE_", 1)[-1] if "RAISE_" in expected else ""
        if key and key in template.data["errors"]:
            # the doctor-facing message comes from the content file's errors block
            assert str(exc.value) == template.data["errors"][key]
        elif key:
            # no errors: entry for this one (e.g. a dose with no word yet) — the message is the
            # renderer's, but it must still name the problem in English for the doctor
            assert str(exc.value).startswith("Read-back blocked")
        return

    rendered = readback.render_line(line, template)
    assert readback.normalise(rendered) == readback.normalise(expected), (
        f"{language}/{example['name']}:\n  got      {rendered!r}\n  expected {expected!r}"
    )


@pytest.mark.parametrize(
    "language,example", CONTENT_EXAMPLES, ids=[f"{lang}-{ex['name']}" for lang, ex in CONTENT_EXAMPLES]
)
def test_every_worked_example_renders_exactly(language, example):
    _run_example(language, example, REAL_CONTENT)


def test_there_are_examples_for_every_language():
    by_language = {language: 0 for language in LANGUAGES}
    for language, _ in CONTENT_EXAMPLES:
        by_language[language] += 1
    assert all(count >= 5 for count in by_language.values()), by_language


def test_every_language_has_a_half_dose_example():
    """docs/04 §2 made half doses legal, so the authority block must cover one."""
    for language in LANGUAGES:
        _needs_every_dose_word(language)
        template = readback.load_template(language, REAL_CONTENT)
        halves = [
            example
            for example in template.examples
            if any(
                float(count) % 1 != 0
                for count in example["rx"]["schedule"].values()
            )
        ]
        assert halves, f"readback/{language}.yaml has no half-dose example"


# ── the same cases against the real content/, once it lands ──────────────────────────────────


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_language_file_carries_an_examples_block(language):
    template = readback.load_template(language, REAL_CONTENT)
    assert template.examples, f"readback/{language}.yaml has no examples: block to be graded by"


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_content_files_are_tagged_for_native_review(language):
    path = REAL_CONTENT / "readback" / f"{language}.yaml"
    text = path.read_text(encoding="utf-8")
    status = (yaml.safe_load(text).get("review") or {}).get("status")
    if status == "signed_off":
        assert "NEEDS-NATIVE-REVIEW" not in text, (
            f"{path} says review.status: signed_off but still carries NEEDS-NATIVE-REVIEW tags"
        )
    else:
        assert "NEEDS-NATIVE-REVIEW" in text, f"{path} has no NEEDS-NATIVE-REVIEW tag"


# ── the contract's structural rules ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_enum_the_type_system_allows_is_covered(language):
    template = readback.load_template(language, REAL_CONTENT)
    for slot in readback.SLOTS:
        assert slot in template.data["time_of_day"]
    for relation in ("before_food", "after_food", "with_food"):
        assert relation in template.data["food_relation"]
    for count in range(1, 5):
        assert count in template.data["count_words"]
    for form in readback.FORM_KEYS:
        assert form in template.data["form_nouns"]
        assert form in template.data["verb_phrase"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_allowed_schedule_and_duration_renders(language):
    """Every integer combination RxLine permits either renders or raises for the stated reason."""
    template = readback.load_template(language, REAL_CONTENT)
    for count in range(0, 5):
        for days in (1, 5, 30, 180, None):
            line = make_line(
                schedule=Schedule(morning=count, afternoon=count, night=count),
                duration_days=days,
                confirmed=True,
            )
            if count == 0:
                with pytest.raises(readback.ReadbackError) as exc:
                    readback.render_line(line, template)
                assert str(exc.value) == template.data["errors"]["all_zero_schedule"]
            else:
                assert readback.render_line(line, template)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_zero_slot_is_silent_never_spoken_as_zero(language):
    template = readback.load_template(language, REAL_CONTENT)
    rendered = readback.render_line(
        make_line(schedule=Schedule(morning=1, afternoon=0, night=0), confirmed=True), template
    )
    assert template.data["time_of_day"]["afternoon"] not in rendered
    assert template.data["time_of_day"]["night"] not in rendered
    assert template.data["count_words"][1] in rendered


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_half_dose_says_the_word_for_half(language):
    """docs/04 §2, changed 2026-10-17: schedule values are multiples of 0.5."""
    _needs_every_dose_word(language)
    template = readback.load_template(language, REAL_CONTENT)
    rendered = readback.render_line(
        make_line(schedule=Schedule(morning=0.5, afternoon=0, night=1), form="tablet",
                  confirmed=True),
        template,
    )
    half = readback._count_table(template.data)[0.5]
    if isinstance(half, dict):  # Hindi: agrees with the form noun's gender
        _, gender = readback._form_entry(template.data, "tablet")
        half = half[gender]
    assert half in rendered
    assert "0.5" not in rendered and "0" not in rendered


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_legal_dose_has_a_word(language):
    """Multiples of 0.5 in 0–4 are all legal, and none of them may be composed or digitised.

    This is the single test that reports a content file which cannot say a legal dose. Such a
    line is blocked at the gate rather than spoken, so the console stays safe — but the doctor
    cannot prescribe it, which is a content gap, not a console one.
    """
    template = readback.load_template(language, REAL_CONTENT)
    table = readback._count_table(template.data)
    missing = [dose for dose in readback.LEGAL_DOSES if dose not in table]
    assert not missing, (
        f"readback/{language}.yaml has no count_words entry for "
        f"{', '.join(readback._show_dose(dose) for dose in missing)}. docs/04 §2 allows every "
        f"multiple of 0.5 in 0–4, so a doctor prescribing one of these is blocked at the gate."
    )
    for dose in readback.LEGAL_DOSES:
        rendered = readback.render_line(
            make_line(schedule=Schedule(morning=dose), form="tablet", confirmed=True), template
        )
        assert rendered
        # the number is a word, never digits — "1.5" must not be read out as a numeral
        assert str(dose) not in rendered


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_fused_half_is_one_word_not_two(language):
    """Tamil and Kannada fuse (ஒன்றரை, ಒಂದೂವರೆ) and Hindi is suppletive (डेढ़) — never one + half."""
    _needs_every_dose_word(language)
    template = readback.load_template(language, REAL_CONTENT)
    table = readback._count_table(template.data)
    one = table[1]
    half = table[0.5]
    if isinstance(half, dict):
        _, gender = readback._form_entry(template.data, "tablet")
        half = half[gender]
    one_and_a_half = table[1.5]
    assert one_and_a_half not in (f"{one} {half}", f"{half} {one}")
    rendered = readback.render_line(
        make_line(schedule=Schedule(morning=1.5), form="tablet", confirmed=True), template
    )
    assert one_and_a_half in rendered


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_dose_with_no_word_blocks_the_readback_rather_than_inventing_one(language, tmp_path):
    """A content file that cannot say a dose blocks that line; it never composes a word."""
    data = yaml.safe_load(
        (REAL_CONTENT / "readback" / f"{language}.yaml").read_text(encoding="utf-8")
    )
    def _is_two_and_a_half(key) -> bool:
        try:
            return float(key) == 2.5
        except (TypeError, ValueError):
            return False  # the literal key "half", which older files use for 0.5

    data["count_words"] = {
        key: value for key, value in data["count_words"].items() if not _is_two_and_a_half(key)
    }
    (tmp_path / "readback").mkdir(exist_ok=True)
    (tmp_path / "readback" / f"{language}.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
    )
    # a missing dose word is a warning at load, not a refusal to start
    template = readback.load_template(language, tmp_path)
    assert readback.render_line(make_line(confirmed=True), template)
    assert 2.5 not in readback._count_table(template.data)

    with pytest.raises(readback.ReadbackError) as exc:
        readback.render_line(
            make_line(schedule=Schedule(morning=2.5), confirmed=True), template
        )
    assert "2.5" in str(exc.value) and "count_words" in str(exc.value)


@pytest.mark.parametrize("language", LANGUAGES)
def test_count_words_are_looked_up_by_value_not_by_string(language):
    """1, 1.0 and 1.00 are the same dose; a str(n) lookup would miss two of them."""
    template = readback.load_template(language, REAL_CONTENT)
    table = readback._count_table(template.data)
    assert table[1] == table[1.0]
    rendered_int = readback.render_line(
        make_line(schedule=Schedule(morning=1), confirmed=True), template
    )
    rendered_float = readback.render_line(
        make_line(schedule=Schedule(morning=1.0), confirmed=True), template
    )
    assert rendered_int == rendered_float


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_count_is_a_word_never_a_digit(language):
    """Tamil's ஒரு is the only form allowed before a noun — str(n) would be ungrammatical."""
    template = readback.load_template(language, REAL_CONTENT)
    rendered = readback.render_line(
        make_line(schedule=Schedule(morning=2, night=0, afternoon=0), duration_days=None,
                  confirmed=True),
        template,
    )
    assert template.data["count_words"][2] in rendered
    assert "2" not in rendered


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_form_noun_and_food_relation_appear_once_on_the_first_clause(language):
    template = readback.load_template(language, REAL_CONTENT)
    rendered = readback.render_line(
        make_line(schedule=Schedule(morning=1, afternoon=1, night=1), food_relation="after_food",
                  form="tablet", confirmed=True),
        template,
    )
    food_word = template.data["food_relation"]["after_food"]
    noun, _ = readback._form_entry(template.data, "tablet")
    assert rendered.count(food_word) == 1
    assert rendered.count(noun) == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_verb_comes_once_at_the_very_end(language):
    """All three languages are SOV: one verb, after the duration, not per clause."""
    template = readback.load_template(language, REAL_CONTENT)
    rendered = readback.render_line(
        make_line(schedule=Schedule(morning=1, afternoon=1, night=1), duration_days=5,
                  form="tablet", confirmed=True),
        template,
    )
    verb = template.data["verb_phrase"]["tablet"]
    end = template.data["punctuation"]["end"]
    assert rendered.count(verb) == 1
    assert rendered.endswith(verb + end)
    duration_word = template.data["duration"]["day_words"][5]
    assert rendered.index(duration_word) < rendered.index(verb)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_null_food_relation_invents_nothing(language):
    template = readback.load_template(language, REAL_CONTENT)
    rendered = readback.render_line(
        make_line(food_relation=None, confirmed=True), template
    )
    for word in template.data["food_relation"].values():
        assert word not in rendered


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_null_form_says_medicine_not_tablet(language):
    template = readback.load_template(language, REAL_CONTENT)
    rendered = readback.render_line(make_line(form=None, confirmed=True), template)
    fallback, _ = readback._form_entry(template.data, None)
    tablet, _ = readback._form_entry(template.data, "tablet")
    assert fallback in rendered
    if tablet != fallback:
        assert tablet not in rendered


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_null_duration_omits_the_duration_clause(language):
    template = readback.load_template(language, REAL_CONTENT)
    rendered = readback.render_line(make_line(duration_days=None, confirmed=True), template)
    assert template.data["duration"]["one_day"] not in rendered
    # the fixed part of the duration phrase ("for N days") must be absent; the number words
    # themselves are shared with count_words, so they are not evidence either way
    tail = template.data["duration"]["template"].replace("{days}", "").strip()
    assert tail not in rendered
    with_duration = readback.render_line(make_line(duration_days=5, confirmed=True), template)
    assert tail in with_duration


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_day_count_with_no_word_falls_back_to_digits(language):
    template = readback.load_template(language, REAL_CONTENT)
    assert template.data["duration"].get("digit_fallback") is True
    assert 23 not in template.data["duration"]["day_words"]
    rendered = readback.render_line(make_line(duration_days=23, confirmed=True), template)
    assert "23" in rendered


def test_only_the_hindi_half_takes_a_gender():
    """0.5 is gender-keyed; 1.5 upward are plain strings, so nothing else needs agreement."""
    _needs_every_dose_word("hi")
    template = readback.load_template("hi", REAL_CONTENT)
    table = readback._count_table(template.data)
    assert isinstance(table[0.5], dict)
    for dose in (1, 1.5, 2, 2.5, 3, 3.5, 4):
        assert isinstance(table[dose], str), f"hi count_words[{dose}] should be a plain string"


def test_hindi_count_and_verb_agree_with_the_form_gender():
    """The renderer looks gender up; it never conjugates anything itself."""
    template = readback.load_template("hi", REAL_CONTENT)
    feminine, gender_f = readback._form_entry(template.data, "tablet")
    masculine, gender_m = readback._form_entry(template.data, "capsule")
    assert (gender_f, gender_m) == ("f", "m")
    # 0.5 is the dose that reaches the gendered count_words.half entry
    assert readback._count_word(template.data, 0.5, gender_f) != readback._count_word(
        template.data, 0.5, gender_m
    )
    for form in ("tablet", "capsule"):
        rendered = readback.render_line(make_line(form=form, confirmed=True), template)
        assert rendered.rstrip(template.data["punctuation"]["end"]).endswith(
            template.data["verb_phrase"][form]
        )


@pytest.mark.parametrize("language", LANGUAGES)
def test_notes_are_read_back_verbatim_behind_the_prefix(language):
    """docs/01 §4: `notes` is free text, read back verbatim — the doctor owns the wording."""
    template = readback.load_template(language, REAL_CONTENT)
    rendered = readback.render_line(
        make_line(notes="half tablet if the fever returns", confirmed=True), template
    )
    assert template.data["notes_prefix"] in rendered
    assert "half tablet if the fever returns" in rendered
    assert rendered.index(template.data["notes_prefix"]) > rendered.index(
        template.data["verb_phrase"]["tablet"]
    )


@pytest.mark.parametrize("language", LANGUAGES)
def test_notes_cannot_carry_template_structure(language):
    template = readback.load_template(language, REAL_CONTENT)
    rendered = readback.render_line(
        make_line(notes="{time_of_day}\n{count} x", confirmed=True), template
    )
    assert "{" not in rendered and "}" not in rendered and "\n" not in rendered


# ── several lines: this console's layer, not the per-line contract ───────────────────────────


def test_a_single_line_readback_names_no_drug():
    """Like the brief's model sentence and every examples: case."""
    rendered = readback.render([make_line(confirmed=True)], "ta", REAL_CONTENT)
    assert "Paracetamol" not in rendered


def test_several_lines_are_named_and_joined_in_order():
    first = make_line(id="rx_1", drug_text="Paracetamol", confirmed=True)
    second = make_line(id="rx_2", drug_text="Amoxicillin", form="syrup", confirmed=True,
                       duration_days=3)
    rendered = readback.render([first, second], "ta", REAL_CONTENT)
    assert rendered.index("Paracetamol") < rendered.index("Amoxicillin")


def test_a_drug_name_cannot_smuggle_template_structure():
    line = make_line(drug_text="Para{count}\n{time_of_day}", confirmed=True)
    other = make_line(id="rx_2", drug_text="ORS", confirmed=True)
    rendered = readback.render([line, other], "ta", REAL_CONTENT)
    assert "{" not in rendered and "}" not in rendered and "\n" not in rendered


def test_an_unconfirmed_line_is_never_rendered():
    with pytest.raises(readback.ReadbackError):
        readback.render([make_line(confirmed=False)], "ta", REAL_CONTENT)
    with pytest.raises(readback.ReadbackError):
        readback.render(
            [make_line(confirmed=True), make_line(id="rx_2", confirmed=False)],
            "ta",
            REAL_CONTENT,
        )


# ── loader errors are doctor-facing and specific ─────────────────────────────────────────────


def test_an_unsupported_language_is_a_clear_error():
    with pytest.raises(readback.ReadbackError) as exc:
        readback.render([make_line(confirmed=True)], "te", REAL_CONTENT)
    assert "te" in str(exc.value)


def test_a_missing_content_file_is_a_clear_error(tmp_path):
    with pytest.raises(readback.ReadbackError) as exc:
        readback.load_template("ta", tmp_path)
    assert "not found" in str(exc.value) and "CONSOLE_CONTENT_DIR" in str(exc.value)


@pytest.mark.parametrize(
    "drop",
    ["templates", "time_of_day", "food_relation", "count_words", "form_nouns", "verb_phrase",
     "duration", "notes_prefix", "errors", "joiners", "punctuation"],
)
def test_a_content_file_missing_a_required_key_is_a_clear_error(tmp_path, drop):
    data = yaml.safe_load(
        (REAL_CONTENT / "readback" / "ta.yaml").read_text(encoding="utf-8")
    )
    data.pop(drop)
    (tmp_path / "readback").mkdir()
    (tmp_path / "readback" / "ta.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(readback.ReadbackError) as exc:
        readback.load_template("ta", tmp_path)
    assert drop in str(exc.value)


def test_a_content_file_missing_one_enum_is_a_clear_error(tmp_path):
    data = yaml.safe_load(
        (REAL_CONTENT / "readback" / "ta.yaml").read_text(encoding="utf-8")
    )
    del data["form_nouns"]["null_form"]
    (tmp_path / "readback").mkdir()
    (tmp_path / "readback" / "ta.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(readback.ReadbackError) as exc:
        readback.load_template("ta", tmp_path)
    assert "null_form" in str(exc.value)


def test_review_status_is_reported_per_language():
    statuses = readback.review_status(REAL_CONTENT)
    assert set(statuses) == set(LANGUAGES)
    assert all(status in ("pending", "signed_off") for status in statuses.values())
    assert readback.review_status(Path("/nowhere"))["ta"] == "missing"
