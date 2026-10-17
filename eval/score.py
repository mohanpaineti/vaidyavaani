#!/usr/bin/env python3
"""VaidyaVaani evaluation harness — the numbers the judges get.

Covers the metrics table in docs/01 §7 and the verification plan in docs/02 §10.

    python eval/score.py all                     # everything, with the fixtures
    python eval/score.py all --log build/livekit/dev.log --runs eval/runs.json
    python eval/score.py review-sheet -o sheet.csv   # for the native speaker
    python eval/score.py score --sheet sheet.csv     # after they fill it in
    python eval/score.py verbatim                # the central safety number
    python eval/score.py teachback
    python eval/score.py halfstep                # the half-step safety suite
    python eval/score.py fixture-drift           # fixtures vs the real content
    python eval/score.py redflags
    python eval/score.py review-status           # how much is still unreviewed
    python eval/score.py latency

What this harness WILL NOT do: score translation accuracy itself. docs/01 §7
says "scored meaning-kept yes/no by a native speaker on the team". A model
grading its own translation is not a measurement, so `review-sheet` emits a
sheet a human fills in and `score` reads it back. If the sheet is missing,
translation accuracy is reported as "not measured" — never estimated.

Exit code: 1 only when a gate that MUST hold has failed — a critical error, or
a teach-back case that was not caught. A verbatim deviation is REPORTED, not
gated: docs/02 §1.4 commits us to saying so rather than hiding it.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import devlog  # noqa: E402
import dose_words  # noqa: E402
import readback_render as rr  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"
CONTENT = ROOT / "content"
LANGS = ("ta", "kn", "hi")
SLOTS = ("morning", "afternoon", "night")
REVIEW_TAG = "NEEDS-NATIVE-REVIEW"

GREEN, RED, YELLOW, DIM, BOLD, OFF = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"
)
if not sys.stdout.isatty():
    GREEN = RED = YELLOW = DIM = BOLD = OFF = ""


def head(title: str) -> None:
    print(f"\n{BOLD}── {title} {'─' * max(0, 66 - len(title))}{OFF}")


def norm(s: str) -> str:
    return " ".join(unicodedata.normalize("NFC", s or "").split())


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def load_sentences() -> list[dict]:
    rows = []
    for lang in LANGS:
        path = EVAL / "sentences" / f"{lang}.csv"
        with path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                r["language"] = lang
                rows.append(r)
    return rows


def load_prescriptions() -> list[dict]:
    with (EVAL / "prescriptions.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["lines"] = json.loads(r["expected_lines_json"])
    return rows


def parse_dev_log(path: Path) -> list[dict]:
    """Tolerant JSONL reader. The real dev.log mixes JSON records with plain
    log lines, so anything that is not a JSON object is skipped silently."""
    records = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records


# ---------------------------------------------------------------------------
# 1. review status — how much of the content is still unverified
# ---------------------------------------------------------------------------

def cmd_review_status(_args) -> int:
    head("Native-speaker review status")
    total = 0
    for path in sorted(list(CONTENT.rglob("*.yaml")) + list(EVAL.rglob("*.csv"))):
        text = path.read_text(encoding="utf-8")
        n = text.count(REVIEW_TAG)
        if n:
            total += n
            print(f"  {n:>4} {REVIEW_TAG}  {path.relative_to(ROOT)}")
    print()
    if total:
        print(f"  {YELLOW}{total} strings still awaiting native-speaker sign-off.{OFF}")
        print(f"  {DIM}A reviewer clears one by correcting the string and deleting its tag.{OFF}")
        print(f"  {DIM}Until this is 0, no patient-facing string here is verified — say so.{OFF}")
    else:
        print(f"  {GREEN}All tags cleared.{OFF} Check `review: status:` in each file names who signed off.")
    print(f"\n  {DIM}Separately: content/redflags/* are NOT clinically reviewed, and clearing")
    print(f"  a language tag does not change that. docs/01 §5 keeps that work for later.{OFF}")
    return 0


# ---------------------------------------------------------------------------
# 2. translation accuracy — a sheet a human fills in, then reads back
# ---------------------------------------------------------------------------

SHEET_COLUMNS = [
    "id", "language", "hard_case", "sentence", "roman", "expected_english",
    "must_keep", "must_not_say", "observed_english",
    "meaning_kept_yes_no", "critical_error_yes_no", "critical_error_kind", "reviewer_note",
]


def cmd_review_sheet(args) -> int:
    rows = load_sentences()
    observed: dict[str, str] = {}
    if args.observed:
        with Path(args.observed).open(encoding="utf-8") as f:
            observed = {r["id"]: r.get("observed_english", "") for r in csv.DictReader(f)}
    out = Path(args.out)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SHEET_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({
                "id": r["id"], "language": r["language"], "hard_case": r["hard_case"],
                "sentence": r["sentence"], "roman": r["roman"],
                "expected_english": r["expected_english"],
                "must_keep": r["must_keep"], "must_not_say": r["must_not_say"],
                "observed_english": observed.get(r["id"], ""),
                "meaning_kept_yes_no": "", "critical_error_yes_no": "",
                "critical_error_kind": "", "reviewer_note": "",
            })
    head("Review sheet written")
    print(f"  {out}  ({len(rows)} sentences)")
    print(f"""
  Give this to the native speaker for each language. For every row they:
    1. read `sentence` aloud into the running app (or paste `observed_english`
       from the run),
    2. set meaning_kept_yes_no = yes only if the ENGLISH carries the same
       meaning — wording may differ, meaning may not,
    3. set critical_error_yes_no = yes if the English has a wrong drug, a wrong
       dose, a wrong timing, or a FLIPPED NEGATION, and say which in
       critical_error_kind (drug|dose|timing|negation|invention),
    4. check `must_keep` facts are all present and no `must_not_say` item appears.

  Then: python eval/score.py score --sheet {out}""")
    return 0


def cmd_score(args) -> int:
    sheet = Path(args.sheet)
    head("Translation accuracy and critical errors (docs/01 §7)")
    if not sheet.exists():
        print(f"  {YELLOW}NOT MEASURED{OFF} — no filled review sheet at {sheet}.")
        print(f"  {DIM}This number is a human judgement by design. Do not estimate it,")
        print(f"  and do not put a figure on a slide that nobody scored.{OFF}")
        return 0
    if "sample" in sheet.name:
        print(f"  {YELLOW}Using the SAMPLE sheet ({sheet.name}). Its verdicts are invented so")
        print(f"  that this command can be exercised. Nothing below is a real result.{OFF}\n")
    with sheet.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_lang: dict[str, list[dict]] = {}
    for r in rows:
        by_lang.setdefault(r["language"], []).append(r)

    unscored = [r for r in rows if r["meaning_kept_yes_no"].strip().lower() not in ("yes", "no")]
    criticals = [r for r in rows if r["critical_error_yes_no"].strip().lower() == "yes"]

    print(f"  {'lang':<6}{'scored':>8}{'kept':>8}{'%':>8}")
    for lang in LANGS:
        rs = by_lang.get(lang, [])
        scored = [r for r in rs if r["meaning_kept_yes_no"].strip().lower() in ("yes", "no")]
        kept = [r for r in scored if r["meaning_kept_yes_no"].strip().lower() == "yes"]
        pct = f"{100 * len(kept) / len(scored):.0f}%" if scored else "—"
        print(f"  {lang:<6}{len(scored):>8}{len(kept):>8}{pct:>8}")
    if unscored:
        print(f"\n  {YELLOW}{len(unscored)} rows not yet scored{OFF} "
              f"({', '.join(r['id'] for r in unscored[:8])}{'…' if len(unscored) > 8 else ''})")
        print(f"  {DIM}Percentages above cover scored rows only. Say that when you quote them.{OFF}")

    head("Critical errors — must be ZERO past the confirm gate")
    if criticals:
        for r in criticals:
            print(f"  {RED}CRITICAL{OFF} {r['id']} [{r['critical_error_kind'] or 'unspecified'}] "
                  f"{r['observed_english'][:70]}")
            if r["reviewer_note"]:
                print(f"           {DIM}{r['reviewer_note']}{OFF}")
        print(f"\n  {RED}{len(criticals)} critical error(s).{OFF} docs/01 §7 target is zero "
              f"reaching the patient — check each one was caught at the confirm gate.")
        return 1
    print(f"  {GREEN}0 critical errors in {len(rows)} scored sentences.{OFF}")
    return 0


# ---------------------------------------------------------------------------
# 3. verbatim read-back — the evidence behind the central safety claim
# ---------------------------------------------------------------------------

SYNTH_WARNING = (
    "SYNTHESIZED FIXTURE — not a recording of a real turn. No live turn has ever\n"
    "  run (docs/00 §3), so nothing below is a measurement. It proves the harness\n"
    "  works, nothing more. Regenerate with eval/make_dev_log_fixture.py."
)


def _log_banner(log_path: Path) -> None:
    """Say loudly when the numbers that follow came from the fixture."""
    if log_path.resolve() == (EVAL / "fixtures" / "dev.log").resolve():
        print(f"  {YELLOW}{SYNTH_WARNING}{OFF}")


def _readback_utterances(log, call_id: str, loose: bool) -> tuple[list[dict], str]:
    """The agent speech that is the read-back, and how we decided that.

    There is no `task` field in a real dev.log — the generated emitter writes
    none (docs/03 §14), so selecting on `task == "read_back"` can never match.
    What the log does carry is the gate's `readback_text` landing in the agent's
    state, so anything the agent speaks after that point is the read-back.
    """
    utts = log.utterances(call_id)
    marks = log.state_changes(call_id, "readback_text")
    if marks:
        after = [u for u in utts if u["order"] > marks[-1]["order"]]
        if after:
            return after, "after the readback_text state change"
    if loose:
        return utts[-1:], "--loose-task-match: the agent's last utterance"
    return [], "no readback_text state change in this call"


def cmd_verbatim(args) -> int:
    log_path = Path(args.log)
    runs_path = Path(args.runs)
    head("Verbatim read-back check (docs/02 §1.4, §10)")
    print(f"  {DIM}log:  {log_path}")
    print(f"  runs: {runs_path}{OFF}")
    _log_banner(log_path)
    if not log_path.exists():
        print(f"\n  {YELLOW}NOT MEASURED{OFF} — no dev.log at {log_path}.")
        print(f"  {DIM}Run the 10 prescriptions under `unmute dev`, then point --log at")
        print(f"  build/livekit/dev.log. Without it there is no evidence for the claim.{OFF}")
        return 0
    if not runs_path.exists():
        print(f"\n  {RED}Cannot map calls to prescriptions: {runs_path} missing.{OFF}")
        return 0

    log = devlog.DevLog.read(log_path)
    if not len(log):
        print(f"\n  {RED}{log_path} parsed to zero records.{OFF} Records are sentinel-prefixed")
        print(f"  {DIM}(`UNMUTE_METRIC {{json}}`) and UNMUTE_DEV_METRICS must be set when the")
        print(f"  worker runs, or nothing is emitted at all (docs/03 §14).{OFF}")
        return 0

    runs = json.loads(runs_path.read_text(encoding="utf-8"))["sessions"]
    rx_by_id = {r["id"]: r for r in load_prescriptions()}
    if args.loose_task_match:
        print(f"  {YELLOW}--loose-task-match: falling back to the agent's last utterance.{OFF}")

    exact = lenient = deviated = 0
    lines_exact = lines_total = 0
    gate_mismatch: list[str] = []
    missing: list[str] = []
    deviations: list[tuple[str, str, str]] = []

    for call_id, meta in sorted(runs.items(), key=lambda kv: (kv[1]["prescription_id"],
                                                              kv[1]["language"])):
        rid, lang = meta["prescription_id"], meta["language"]
        rx = rx_by_id.get(rid)
        if rx is None:
            missing.append(f"{rid} (no such row in prescriptions.csv)")
            continue
        label = f"{rid}/{lang}"
        try:
            expected = rr.render_prescription(rx["lines"], lang)
        except rr.ReadbackError as exc:
            missing.append(f"{label}: the template render itself failed — {exc}")
            continue
        utts, how = _readback_utterances(log, call_id, args.loose_task_match)
        if not utts:
            missing.append(f"{label}: {how}")
            continue

        # The gate hands the agent ONE readback_text for the whole prescription
        # (console/app/readback.py), so the spoken unit is the prescription, not
        # the line. Comparing line by line reports a deviation on every
        # multi-line row and finds nothing real.
        got = "".join(u["text"] for u in utts)
        if any(u["incomplete"] for u in utts):
            print(f"  {YELLOW}{label}: the spoken text was cut off (state: incomplete).{OFF}")
        if got == expected:
            exact += 1
        elif norm(got) == norm(expected):
            lenient += 1
            deviations.append((f"{label} (normalisation only)", expected, got))
        else:
            deviated += 1
            deviations.append((label, expected, got))

        # Per-line coverage, which is the number docs/01 §9 quotes: 11 confirmed
        # RxLines across the 10 rows, x3 languages.
        for line in rx["lines"]:
            lines_total += 1
            if norm(rr.render(line, lang)) in norm(got):
                lines_exact += 1

        # The gate's own text against eval's independent render. If these two
        # disagree the console and eval have read the contract differently, and
        # that is a finding whatever the agent then said.
        marks = log.state_changes(call_id, "readback_text")
        if marks and norm(str(marks[-1]["value"])) != norm(expected):
            gate_mismatch.append(label)

    total = exact + lenient + deviated
    print(f"\n  prescription runs checked              : {total}")
    print(f"  byte-identical to the template render : {exact}/{total}")
    print(f"  identical after NFC + whitespace      : {exact + lenient}/{total}")
    print(f"  deviated                              : {deviated}/{total}")
    print(f"  confirmed RxLines spoken verbatim     : {lines_exact}/{lines_total}")
    if missing:
        print(f"  {YELLOW}no spoken text found for {len(missing)} run(s){OFF}")
        for m in missing:
            print(f"    - {m}")
    if gate_mismatch:
        print(f"\n  {RED}The gate's readback_text differs from eval's independent render{OFF} "
              f"in {len(gate_mismatch)} run(s): {', '.join(gate_mismatch)}")
        print(f"  {DIM}console/app/readback.py and eval/readback_render.py have read the")
        print(f"  render contract differently. One of them is wrong.{OFF}")

    for label, expected, got in deviations:
        print(f"\n  {RED}DEVIATION{OFF} {label}")
        print(f"    template render : {expected}")
        print(f"    actually spoken : {got}")
        print(f"    {DIM}{_first_diff(expected, got)}{OFF}")

    print()
    if deviated == 0 and not missing and total:
        print(f"  {GREEN}Every read-back was spoken exactly as the template rendered it.{OFF}")
        print(f"  {DIM}This is the sentence to say on stage, and only while it stays true.{OFF}")
    elif total:
        print(f"  {YELLOW}Say this on stage as it is.{OFF} docs/02 §1.4: a cascade agent speaks")
        print(f"  {DIM}through the LLM, so this is verbatim-read WITH A MEASURED CHECK, not a")
        print(f"  byte-level guarantee. Reporting the deviation is the honest answer; the")
        print(f"  fallback in docs/02 §11 is to speak only the digits-and-icons card.{OFF}")
    # Deliberately not a gate — see the module docstring.
    return 0


def _first_diff(a: str, b: str) -> str:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return f"first difference at character {i}: {a[i:i + 24]!r} vs {b[i:i + 24]!r}"
    if len(a) != len(b):
        longer, shorter = (a, b) if len(a) > len(b) else (b, a)
        who = "template" if len(a) > len(b) else "spoken"
        return f"{who} has {len(longer) - len(shorter)} extra characters: {longer[len(shorter):][:40]!r}"
    return "strings differ only in Unicode normalisation or whitespace"


# ---------------------------------------------------------------------------
# 4. teach-back catch rate
# ---------------------------------------------------------------------------

def compare_teachback(confirmed: dict, patient_said: dict, lang: str | None = None) -> dict:
    """Reference field-by-field comparison (docs/04 §2 TeachBackResult).

    Numbers are compared arithmetically. A field the patient did not mention is
    `not_mentioned`, which is NOT a mismatch — a patient repeating only part of
    the plan has not got it wrong.
    """
    line_id = confirmed["id"]
    per_line = {"line_id": line_id, "patient_said": patient_said}
    mismatched = []
    for slot in SLOTS:
        if slot not in patient_said:
            per_line[slot] = "not_mentioned"
            continue
        # float, NOT int: schedule values are multiples of 0.5 since the
        # docs/04 §2 change of 2026-10-17, and int(0.5) == int(0) would call a
        # patient who heard "one" for a prescribed half a MATCH. That is the
        # exact double-dose error teach-back exists to catch.
        #
        # The value may also be WORDS — "half a tablet", or the patient's own
        # word for it — because that is what a patient says. parse_count owns
        # that, and raises rather than guessing: docs/00 §7's second bug was a
        # parser quietly answering 0 for "half", which scored a prescribed zero
        # against a patient saying half as a match. An unparseable count is a
        # mismatch here, never a match.
        try:
            said = dose_words.parse_count(patient_said[slot], lang)
        except dose_words.DoseWordError as exc:
            per_line[slot] = "mismatch"
            per_line.setdefault("unparsed", []).append(f"{slot}: {exc}")
            mismatched.append(f"{line_id}.{slot}")
            continue
        verdict = "match" if said == float(confirmed["schedule"][slot]) else "mismatch"
        per_line[slot] = verdict
        if verdict == "mismatch":
            mismatched.append(f"{line_id}.{slot}")
    if "duration_days" not in patient_said or patient_said["duration_days"] is None:
        per_line["duration"] = "not_mentioned"
    elif int(patient_said["duration_days"]) == int(confirmed["duration_days"] or -1):
        per_line["duration"] = "match"
    else:
        per_line["duration"] = "mismatch"
        mismatched.append(f"{line_id}.duration")
    if "food_relation" not in patient_said:
        per_line["food_relation"] = "not_mentioned"
    elif patient_said["food_relation"] == confirmed["food_relation"]:
        per_line["food_relation"] = "match"
    else:
        per_line["food_relation"] = "mismatch"
        mismatched.append(f"{line_id}.food_relation")
    return {
        "overall": "mismatch" if mismatched else "match",
        "per_line": [per_line],
        "mismatched_fields": mismatched,
    }


def cmd_teachback(args) -> int:
    head("Teach-back catch rate (docs/01 §7 — target 5/5)")
    data = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    wrong = [c for c in data["cases"] if c["expect_overall"] == "mismatch"]
    controls = [c for c in data["cases"] if c["expect_overall"] == "match"]
    caught = 0
    failures = 0
    for case in data["cases"]:
        result = compare_teachback(case["confirmed"], case["patient_said"])
        ok_overall = result["overall"] == case["expect_overall"]
        ok_fields = sorted(result["mismatched_fields"]) == sorted(case["expect_mismatched_fields"])
        mark = f"{GREEN}OK  {OFF}" if (ok_overall and ok_fields) else f"{RED}FAIL{OFF}"
        if case["expect_overall"] == "mismatch" and result["overall"] == "mismatch":
            caught += 1
        if not (ok_overall and ok_fields):
            failures += 1
        fields = ", ".join(result["mismatched_fields"]) or "—"
        print(f"  {mark} {case['id']:<14} {case['why_wrong'][:52]:<52} flagged: {fields}")

    print(f"\n  caught {caught}/{len(wrong)} seeded wrong read-backs")
    print(f"  {len(controls)} control case(s) that must NOT flag: "
          f"{GREEN if all(compare_teachback(c['confirmed'], c['patient_said'])['overall'] == 'match' for c in controls) else RED}"
          f"{'clean' if all(compare_teachback(c['confirmed'], c['patient_said'])['overall'] == 'match' for c in controls) else 'OVER-FLAGGED'}{OFF}")
    print(f"  {DIM}This exercises eval's reference comparator. console/tests/test_teachback.py")
    print(f"  must run the same cases through console/app/teachback.py — if the two")
    print(f"  disagree, the number on the slide is from the wrong implementation.{OFF}")
    if caught < len(wrong) or failures:
        print(f"\n  {RED}Gate failed: not every seeded error was caught as specified.{OFF}")
        return 1
    print(f"\n  {GREEN}{caught}/{len(wrong)} — matches the docs/01 §7 target.{OFF}")
    return 0


# ---------------------------------------------------------------------------
# 4b. half-steps — the two §7 bugs, and a suite they cannot survive
# ---------------------------------------------------------------------------

def _resolve_count_word(value, lang: str):
    """`@count_word:0.5` -> the patient's own word for a half, read live from
    content/readback/<lang>.yaml. There is deliberately no copy of that table
    in eval: a drifted copy is how the "1.5 has no word" false diagnosis
    happened (docs/00 §6)."""
    if isinstance(value, str) and value.startswith("@count_word:"):
        wanted = float(value.split(":", 1)[1])
        for word, dose in dose_words.language_words(lang).items():
            if dose == wanted:
                return word
        raise rr.ReadbackError(
            f"content/readback/{lang}.yaml has no count word for {wanted}")
    return value


def _broken_int_comparator(confirmed: dict, patient_said: dict, lang: str | None = None) -> dict:
    """docs/00 §7 bug 1, restored on purpose: int() truncation."""
    said = {k: (int(float(dose_words.parse_count(v, lang))) if k in SLOTS else v)
            for k, v in patient_said.items()}
    truncated = dict(confirmed)
    truncated["schedule"] = {k: int(v) for k, v in confirmed["schedule"].items()}
    return compare_teachback(truncated, said, lang)


def _broken_half_is_zero_comparator(confirmed: dict, patient_said: dict,
                                    lang: str | None = None) -> dict:
    """docs/00 §7 bug 2, restored on purpose: the word "half" parsed as 0."""
    halves = {w for w, v in (dose_words.language_words(lang) if lang else {}).items() if v == 0.5}
    said = {}
    for k, v in patient_said.items():
        if k in SLOTS and isinstance(v, str) and ("half" in v.lower() or v.lower() in halves):
            said[k] = 0
        else:
            said[k] = v
    return compare_teachback(confirmed, said, lang)


def cmd_halfstep(args) -> int:
    """Half-step coverage in every language, plus proof the suite has teeth.

    docs/00 §7: the same safety bug turned up in two layers the day Schedule
    became multiples of 0.5 — int() truncation in the comparator, and the word
    "half" parsed as 0 in the extractor. Both silent, both a wrong dose scored
    as understood, and neither would EVER fire on a whole-number case. So this
    suite is all half-steps, and it ends by re-running itself through both
    broken implementations: if either survives, the suite is not a suite and
    this command fails.
    """
    head("Half-step doses (docs/00 §7) — every language")
    data = json.loads(Path(args.halfstep).read_text(encoding="utf-8"))
    langs = tuple(data["languages"])
    problems = 0

    print(f"  {DIM}renders — a half must be the language's own word, never a digit{OFF}")
    for case in data["render_cases"]:
        for lang in langs:
            try:
                sentence = rr.render_prescription([case["rx"]], lang)
            except rr.ReadbackError as exc:
                problems += 1
                print(f"  {RED}FAIL{OFF} {case['id']}/{lang}: does not render — {exc}")
                continue
            table = rr.load(lang)["count_words"]
            word = table[case["must_use_count"]]
            forms = list(word.values()) if isinstance(word, dict) else [word]
            if not any(norm(f) in norm(sentence) for f in forms):
                problems += 1
                print(f"  {RED}FAIL{OFF} {case['id']}/{lang}: {case['must_use_count']} did not "
                      f"reach the sentence as any of {forms}\n       {sentence}")
                continue
            print(f"  {GREEN}OK  {OFF} {case['id']:<26}{lang}  {sentence}")

    print(f"\n  {DIM}parsing — what the patient says back, in English or their own words{OFF}")
    for case in data["parse_cases"]:
        for lang in langs:
            phrase = _resolve_count_word(case["phrase"], lang)
            try:
                got = dose_words.parse_count(phrase, lang)
            except dose_words.DoseWordError as exc:
                got = f"RAISED ({exc})"
            if got != case["expect"]:
                problems += 1
                print(f"  {RED}FAIL{OFF} {lang} {phrase!r} -> {got!r}, expected "
                      f"{case['expect']!r}  {case['why']}")
    print(f"  {len(data['parse_cases'])} phrases x {len(langs)} languages parsed")

    print(f"\n  {DIM}teach-back on half-steps{OFF}")
    cases = []
    for case in data["teachback_cases"]:
        for lang in langs:
            said = {k: _resolve_count_word(v, lang) for k, v in case["patient_said"].items()}
            cases.append((f"{case['id']}/{lang}", lang, case, said))
    for label, lang, case, said in cases:
        result = compare_teachback(case["confirmed"], said, lang)
        ok = (result["overall"] == case["expect_overall"]
              and sorted(result["mismatched_fields"]) == sorted(case["expect_mismatched_fields"]))
        if not ok:
            problems += 1
            print(f"  {RED}FAIL{OFF} {label}: got {result['overall']} "
                  f"{result['mismatched_fields']}, expected {case['expect_overall']} "
                  f"{case['expect_mismatched_fields']}\n       {case['why_wrong']}")
    caught = sum(1 for label, lang, case, said in cases
                 if case["expect_overall"] == "mismatch"
                 and compare_teachback(case["confirmed"], said, lang)["overall"] == "mismatch")
    wrong = sum(1 for _, _, case, _ in cases if case["expect_overall"] == "mismatch")
    print(f"  caught {caught}/{wrong} half-step errors; "
          f"{len(cases) - wrong} control case(s) that must not flag")

    # The part that matters: a suite a known-broken comparator can pass is not
    # a suite. Each broken implementation below MUST be caught by some case.
    print(f"\n  {DIM}mutation check — the suite against the two bugs docs/00 §7 records{OFF}")
    everything = cases + [(c["id"], c.get("language"), c, c["patient_said"])
                          for c in json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]]
    for name, broken, bug in (
        ("int() truncation", _broken_int_comparator, "docs/00 §7 bug 1"),
        ('"half" parsed as 0', _broken_half_is_zero_comparator, "docs/00 §7 bug 2"),
    ):
        survivors = []
        for label, lang, case, said in everything:
            try:
                result = broken(case["confirmed"], said, lang)
            except Exception:  # noqa: BLE001 - a broken comparator blowing up is a catch
                continue
            if (result["overall"] != case["expect_overall"]
                    or sorted(result["mismatched_fields"]) != sorted(case["expect_mismatched_fields"])):
                continue  # caught: the broken comparator gets this case wrong
            survivors.append(label)
        if len(survivors) == len(everything):
            problems += 1
            print(f"  {RED}FAIL{OFF} {name} ({bug}) passes every case in the suite. "
                  f"The suite cannot see the bug it exists for.")
        else:
            print(f"  {GREEN}OK  {OFF} {name} ({bug}) is caught by "
                  f"{len(everything) - len(survivors)}/{len(everything)} cases")

    print()
    if problems:
        print(f"  {RED}{problems} half-step problem(s).{OFF} These are the silent ones — a "
              f"wrong dose recorded as understood.")
        return 1
    print(f"  {GREEN}Half-steps hold in all {len(langs)} languages, and a whole-number-only")
    print(f"  comparator cannot pass this suite.{OFF}")
    return 0


# ---------------------------------------------------------------------------
# 4c. fixture drift — the stale-copy failure mode, made impossible to miss
# ---------------------------------------------------------------------------

def cmd_fixture_drift(_args) -> int:
    """Fail loudly when a fixture no longer matches the real content files.

    docs/00 §6: a stale fixture copy of the content produced a "1.5 doses have
    no word" diagnosis that was wrong in both directions and cost two round
    trips. The defence here is twofold — eval keeps NO copy of the content
    (readback_render.py reads content/ directly), and the one fixture that does
    embed rendered strings, fixtures/dev.log, is a derived artifact with a
    generator. This regenerates it in memory and diffs.
    """
    head("Fixture drift against the real content files")
    problems = 0

    copies = [p for p in EVAL.rglob("*.yaml")
              if "count_words" in p.read_text(encoding="utf-8")]
    if copies:
        problems += 1
        for path in copies:
            print(f"  {RED}FAIL{OFF} {path.relative_to(ROOT)} looks like a copy of a "
                  f"content/readback template. Read content/ directly instead — a copy "
                  f"is the docs/00 §6 failure.")
    else:
        print(f"  {GREEN}OK  {OFF} eval holds no copy of content/readback/* "
              f"(readback_render.py reads the real files)")

    sys.path.insert(0, str(EVAL))
    import make_dev_log_fixture as gen
    want_log, want_runs = gen.build()
    for name, want in (("dev.log", want_log),
                       ("runs.json", json.dumps(want_runs, indent=2, ensure_ascii=False) + "\n")):
        path = EVAL / "fixtures" / name
        got = path.read_text(encoding="utf-8") if path.exists() else ""
        if got == want:
            print(f"  {GREEN}OK  {OFF} eval/fixtures/{name} matches what the content renders today")
            continue
        problems += 1
        print(f"  {RED}STALE{OFF} eval/fixtures/{name} no longer matches the content files.")
        for line_no, (a, b) in enumerate(zip(got.splitlines(), want.splitlines()), 1):
            if a != b:
                print(f"    first difference, line {line_no}:")
                print(f"      committed : {a[:120]}")
                print(f"      renders to: {b[:120]}")
                break
        else:
            print(f"    committed file has {len(got.splitlines())} lines, "
                  f"the content renders {len(want.splitlines())}")
        print(f"    {DIM}Regenerate: python3 -I eval/make_dev_log_fixture.py{OFF}")

    print()
    if problems:
        print(f"  {RED}{problems} drift problem(s).{OFF} Until this is clean, a verbatim")
        print(f"  deviation may be nothing but the fixture rotting — which is exactly the")
        print(f"  wrong thing to discover while reading a number off a slide.")
        return 1
    print(f"  {GREEN}No drift. Every rendered string in the fixtures is what content/ says today.{OFF}")
    return 0


# ---------------------------------------------------------------------------
# 5. red-flag keyword layer — does layer 1 fire where it should, and stay quiet
#    where a negation says it should?
# ---------------------------------------------------------------------------

def match_red_flags(text: str, flags: list[dict]) -> tuple[set[str], set[str]]:
    """Layer-1 matching, exactly as console/app should do it (see the rules in
    content/redflags/en.yaml). Returns (fired, suppressed_by_negation)."""
    hay = norm(text).lower()
    fired, suppressed = set(), set()
    for flag in flags:
        hits = [p for p in flag["phrases"] if norm(p).lower() in hay]
        if not hits:
            continue
        guards = [g for g in flag.get("negation_guards") or [] if norm(g).lower() in hay]
        # Longest-match wins: a guard only suppresses if it is at least as long
        # as the matched phrase. "खून बंद नहीं हो रहा" must beat the guard "खून नहीं".
        longest_hit = max(len(norm(h)) for h in hits)
        if guards and max(len(norm(g)) for g in guards) >= longest_hit:
            suppressed.add(flag["id"])
        else:
            fired.add(flag["id"])
    return fired, suppressed


def cmd_redflags(args) -> int:
    import yaml
    head("Red-flag keyword layer vs the eval sentences")
    print(f"  {YELLOW}Reminder: content/redflags/* is NOT clinically reviewed (docs/01 §5).{OFF}")
    print(f"  {DIM}This measures whether the matcher does what the file says, nothing more.{OFF}\n")
    bad = 0
    for lang in LANGS:
        flags = yaml.safe_load((CONTENT / "redflags" / f"{lang}.yaml").read_text(encoding="utf-8"))["flags"]
        rows = [r for r in load_sentences() if r["language"] == lang]
        for r in rows:
            fired, suppressed = match_red_flags(r["sentence"], flags)
            want = r["expect_red_flag"].strip()
            want_set = set() if want in ("", "none") else {want}
            if fired == want_set:
                continue
            bad += 1
            extra = ", ".join(sorted(fired - want_set)) or "—"
            miss = ", ".join(sorted(want_set - fired)) or "—"
            print(f"  {YELLOW}{r['id']}{OFF} expected [{want or 'none'}]  "
                  f"fired [{', '.join(sorted(fired)) or 'none'}]  missed [{miss}]  extra [{extra}]")
            if suppressed:
                print(f"      {DIM}suppressed by a negation guard: {', '.join(sorted(suppressed))}{OFF}")
    print()
    if bad:
        print(f"  {YELLOW}{bad}/60 sentences did not match the expectation.{OFF}")
        print(f"  {DIM}Layer 1 is allowed to over-flag and to miss two-fact flags — layer 2")
        print(f"  (the LLM's red_flags[]) resolves those. Treat this as a tuning list, not")
        print(f"  a pass/fail: the one case that IS a defect is a flag firing on a denial.{OFF}")
    else:
        print(f"  {GREEN}All 60 sentences matched their expected flag.{OFF}")
    return 0


# ---------------------------------------------------------------------------
# 6. latency, straight out of the measurement records
# ---------------------------------------------------------------------------

def cmd_latency(args) -> int:
    head("Turn latency from dev.log measurement records (docs/01 §7, docs/02 §7)")
    log_path = Path(args.log)
    _log_banner(log_path)
    log = devlog.DevLog.read(log_path)
    if not len(log):
        print(f"  {YELLOW}NOT MEASURED{OFF} — no records parsed from {log_path}.")
        print(f"  {DIM}Records are `UNMUTE_METRIC {{json}}` lines and UNMUTE_DEV_METRICS must")
        print(f"  be set on the worker, or nothing is emitted at all (docs/03 §14).{OFF}")
        return 0

    # Values are in SECONDS (docs/03 §14 trap 1), deduped by id at the highest
    # revision (trap 4), and `unavailable` records carry no value at all and are
    # skipped rather than read as zero (trap 5).
    values = [v * 1000 for v in log.measurements("reply_latency")]
    if not values:
        print(f"  {YELLOW}NOT MEASURED{OFF} — {len(log)} records parsed, none of them "
              f"a measured reply_latency.")
        return 0
    values.sort()
    p90 = values[min(len(values) - 1, int(round(0.9 * (len(values) - 1))))]
    print(f"  turns      : {len(values)}")
    print(f"  median     : {statistics.median(values):.0f} ms")
    print(f"  p90        : {p90:.0f} ms")
    print(f"  worst      : {max(values):.0f} ms")
    print(f"\n  {DIM}LiveKit's own bands (docs/02 §7), which we quote rather than invent:")
    print(f"  green <= 900 ms · slow > 900 ms · over limit > 1200 ms{OFF}")
    over = sum(1 for v in values if v > 1200)
    slow = sum(1 for v in values if 900 < v <= 1200)
    print(f"  green {len(values) - slow - over} · slow {slow} · over limit {over}")

    # One metric name serves two stages: `first_response` is BOTH the LLM's TTFT
    # and the TTS's time-to-first-audio, and only `source` tells them apart
    # (docs/03 §14). Name matching alone silently mixes them.
    print(f"\n  {'stage':<18}{'metric':<22}{'n':>4}{'median ms':>12}{'p90 ms':>10}")
    for tile, (metric, source) in devlog.STAGE_SOURCES.items():
        samples = sorted(v * 1000 for v in log.measurements(metric, source))
        if not samples:
            print(f"  {tile:<18}{metric:<22}{0:>4}{'—':>12}{'—':>10}")
            continue
        tile_p90 = samples[min(len(samples) - 1, int(round(0.9 * (len(samples) - 1))))]
        print(f"  {tile:<18}{metric:<22}{len(samples):>4}"
              f"{statistics.median(samples):>12.0f}{tile_p90:>10.0f}")

    unavailable = log.unavailable()
    if unavailable:
        print(f"\n  {DIM}{len(unavailable)} record(s) the emitter could not measure, skipped")
        print(f"  rather than counted as zero:{OFF}")
        for metric, reason in sorted(set(unavailable)):
            print(f"    {metric}: {reason}")
        print(f"  {DIM}This is why the `stt` tile reads transcription_delay from EOUMetrics")
        print(f"  and not STT metrics — Saaras is streaming, so STT request_duration is")
        print(f"  always unavailable (docs/03 §14).{OFF}")
    return 0


# ---------------------------------------------------------------------------
# 7. content self-check — the files are loadable and conform to docs/04 §2
# ---------------------------------------------------------------------------

def _legal_schedule_value(v) -> bool:
    """docs/04 §2, changed 2026-10-17: multiples of 0.5 in 0-4. 0.25 is not legal."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    return 0 <= v <= 4 and abs(v * 2 - round(v * 2)) < 1e-9


def cmd_content_check(_args) -> int:
    import yaml
    head("Content self-check")
    problems = 0
    for lang in LANGS:
        tpl = rr.load(lang)
        for ex in tpl.get("examples", []):
            try:
                got = rr.render(dict(ex["rx"]), lang)
                ok = got == ex["expect"]
            except rr.ReadbackError:
                got, ok = "RAISE", str(ex["expect"]).startswith("RAISE")
            if not ok:
                problems += 1
                print(f"  {RED}FAIL{OFF} {lang} {ex['name']}\n       want: {ex['expect']}\n       got : {got}")
    # Contract-coverage assertion. docs/04 §2 allows multiples of 0.5 in 0-4;
    # a legal dose with no word in a language file is a 503 at the gate, which
    # means a doctor cannot prescribe it at all. This is how that stays caught
    # here rather than live: it is the failure console-backend hit on 1.5.
    legal = [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4]   # 0 needs no word — the clause is skipped
    for lang in LANGS:
        tpl = rr.load(lang)
        table = {float(k): v for k, v in tpl["count_words"].items()}
        for value in legal:
            word = table.get(value)
            if word is None:
                problems += 1
                print(f"  {RED}FAIL{OFF} content/readback/{lang}.yaml: no count word for {value}, "
                      f"which docs/04 §2 allows — a doctor prescribing it gets blocked at the gate")
                continue
            if isinstance(word, dict):
                # Hindi's gendered entries must cover every gender in form_nouns.
                needed = {e.get("gender") for e in tpl["form_nouns"].values()
                          if isinstance(e, dict) and e.get("gender")}
                for g in sorted(needed - set(word)):
                    problems += 1
                    print(f"  {RED}FAIL{OFF} content/readback/{lang}.yaml: count_words[{value}] "
                          f"has no {g!r} form, but form_nouns has {g!r} nouns")
        # And every value must actually render, not merely be present.
        for value in legal:
            try:
                rr.render({"schedule": {"morning": value, "afternoon": 0, "night": 0},
                           "food_relation": "after_food", "form": "tablet",
                           "duration_days": 5, "notes": None}, lang)
            except rr.ReadbackError as exc:
                problems += 1
                print(f"  {RED}FAIL{OFF} {lang}: dose {value} does not render — {exc}")
    print(f"  schedule-value coverage: {len(legal)} legal doses x {len(LANGS)} languages, "
          f"each with a word and a render")

    print(f"  read-back worked examples: "
          f"{sum(len(rr.load(l).get('examples', [])) for l in LANGS)} checked, {problems} failing")

    allowed_unit = {"mg", "ml", "g", "iu", "drops", None}
    allowed_form = {"tablet", "capsule", "syrup", "injection", "drops", "ointment", None}
    allowed_food = {"before_food", "after_food", "with_food", None}
    nlines = 0
    for r in load_prescriptions():
        for L in r["lines"]:
            nlines += 1
            checks = [
                (L["strength_unit"] in allowed_unit, "strength_unit"),
                (L["form"] in allowed_form, "form"),
                (L["food_relation"] in allowed_food, "food_relation"),
                (L["duration_days"] is None or 1 <= L["duration_days"] <= 180, "duration_days"),
                (L["strength_value"] is None or 0 <= L["strength_value"] <= 5000, "strength_value"),
                (all(_legal_schedule_value(v) for v in L["schedule"].values()),
                 "schedule (must be multiples of 0.5 in 0-4)"),
                (sum(L["schedule"].values()) > 0, "schedule all zero — would be unspeakable"),
            ]
            for ok, what in checks:
                if not ok:
                    problems += 1
                    print(f"  {RED}FAIL{OFF} {r['id']}: {what} violates docs/04 §2")
    print(f"  prescription RxLines against docs/04 §2: {nlines} checked")

    for lang in LANGS + ("en",):
        d = yaml.safe_load((CONTENT / "redflags" / f"{lang}.yaml").read_text(encoding="utf-8"))
        if d.get("clinically_reviewed") is not False:
            problems += 1
            print(f"  {RED}FAIL{OFF} content/redflags/{lang}.yaml: clinically_reviewed must stay false "
                  f"until a clinician actually reviews it")
        for f in d["flags"]:
            if f["severity"] not in ("watch", "urgent"):
                problems += 1
                print(f"  {RED}FAIL{OFF} {lang}/{f['id']}: severity must be watch|urgent (docs/04 §2)")
    print(f"  red-flag files: 4 loaded, severities and the not-reviewed marker checked")

    for lang in LANGS:
        g = yaml.safe_load((CONTENT / "glossary" / f"{lang}.yaml").read_text(encoding="utf-8"))
        print(f"  glossary {lang}: {len(g['entries'])} entries")

    sent = load_sentences()
    print(f"  eval sentences: {len(sent)} across {len(LANGS)} languages")
    for lang in LANGS:
        n = sum(1 for r in sent if r["language"] == lang)
        if n != 20:
            problems += 1
            print(f"  {RED}FAIL{OFF} {lang}: {n} sentences, expected 20")

    print()
    if problems:
        print(f"  {RED}{problems} content problem(s).{OFF}")
        return 1
    print(f"  {GREEN}Content files are loadable and conform to docs/04 §2.{OFF}")
    return 0


# ---------------------------------------------------------------------------

def cmd_all(args) -> int:
    rc = 0
    print(f"{BOLD}VaidyaVaani evaluation harness{OFF}")
    print(f"{DIM}docs/01 §7 metrics · docs/02 §10 verification plan{OFF}")
    rc |= cmd_content_check(args)
    rc |= cmd_fixture_drift(args)
    rc |= cmd_verbatim(args)
    rc |= cmd_teachback(args)
    rc |= cmd_halfstep(args)
    rc |= cmd_redflags(args)
    rc |= cmd_latency(args)
    rc |= cmd_score(args)
    cmd_review_status(args)
    head("What these numbers are")
    on_fixture = Path(args.log).resolve() == (EVAL / "fixtures" / "dev.log").resolve()
    if on_fixture:
        print(f"""  {RED}NOTHING ABOVE THAT CAME FROM THE LOG IS MEASURED.{OFF} --log still points at
  {DIM}eval/fixtures/dev.log, which is SYNTHESIZED from the record shapes in docs/03
  §14. No live turn has ever run (docs/00 §3), so the verbatim result and every
  latency above describe the harness, not the system. They prove the instrument
  works before demo day; they are not evidence about the product, and no figure
  from this run belongs on a slide.{OFF}""")
    else:
        print(f"  {GREEN}Log-derived numbers above came from {args.log}.{OFF}")
    print("""
  FROM THE LOG       : verbatim read-back, latency. Real only when --log points
                       at a real build/livekit/dev.log from live runs.
  CHECKED HERE       : teach-back comparator, half-steps, red-flag matching,
                       content conformance, fixture drift. These test our own
                       code and hold whether or not a turn has ever run.
  MEASURED by a human: translation accuracy and critical errors — a native
                       speaker fills the review sheet; this harness only counts.
  NOT MEASURED at all: whether the red-flag lists are clinically correct. They
                       are not clinically reviewed and must not be described
                       as if they were. And 437 patient-facing strings still
                       carry NEEDS-NATIVE-REVIEW, so no string here is verified.""")
    print(f"\n{(GREEN + 'GATES PASSED' + OFF) if rc == 0 else (RED + 'A GATE FAILED — see above' + OFF)}")
    return rc


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--log", default=str(EVAL / "fixtures" / "dev.log"),
                   help="path to build/livekit/dev.log (default: the sample fixture)")
    p.add_argument("--runs", default=str(EVAL / "fixtures" / "runs.json"),
                   help="session_id -> prescription_id map")
    p.add_argument("--cases", default=str(EVAL / "fixtures" / "teachback_cases.json"))
    p.add_argument("--halfstep", default=str(EVAL / "fixtures" / "halfstep_cases.json"))
    p.add_argument("--sheet", default=str(EVAL / "fixtures" / "review_sheet_filled_sample.csv"))
    p.add_argument("--loose-task-match", action="store_true",
                   help="treat any agent utterance as a read-back if the log has no task field")
    sub = p.add_subparsers(dest="cmd")
    for name, fn in [
        ("all", cmd_all), ("content-check", cmd_content_check), ("verbatim", cmd_verbatim),
        ("teachback", cmd_teachback), ("redflags", cmd_redflags), ("latency", cmd_latency),
        ("score", cmd_score), ("review-status", cmd_review_status),
        ("halfstep", cmd_halfstep), ("fixture-drift", cmd_fixture_drift),
    ]:
        sp = sub.add_parser(name)
        sp.set_defaults(fn=fn)
    sp = sub.add_parser("review-sheet")
    sp.add_argument("-o", "--out", default="eval/review_sheet.csv")
    sp.add_argument("--observed", help="CSV with id,observed_english from a run, to pre-fill")
    sp.set_defaults(fn=cmd_review_sheet)
    args = p.parse_args()
    if not getattr(args, "fn", None):
        args.fn = cmd_all
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
