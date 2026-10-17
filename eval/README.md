# eval/ — the numbers the judges get

Everything in `docs/01-product-plan.md` §7 ("metrics we measure on the day, not
estimate") and `docs/02-technical-architecture.md` §10 (verification plan) that
is ours to measure. One command produces the lot.

```bash
pip install -r eval/requirements.txt     # PyYAML, nothing else
python3 -I eval/score.py all             # runs against the sample fixtures
```

> **The default `--log` is a SYNTHESIZED fixture and nothing taken from it is a
> measurement.** No live turn has ever run (docs/00 §3), so `eval/fixtures/dev.log`
> is built by `eval/make_dev_log_fixture.py` from the record shapes in docs/03 §14,
> which were read off the generated emitter. It exists to prove the harness works
> before demo day, so that when a live turn finally runs the only unknown is the
> result and not the tool. `score.py all` says so in red at the end of every run
> while `--log` still points there.

Exit code is `1` only when a gate that must hold has failed: a critical error,
or a seeded teach-back error that was not caught. A verbatim deviation is
**reported, not gated** — `docs/02` §1.4 commits us to saying so out loud
rather than hiding it behind a pass.

---

## Demo day, in order

**The day before — content review (the long pole).**

```bash
python eval/score.py review-status
```

Prints how many strings still carry `NEEDS-NATIVE-REVIEW`. Every patient-facing
string in `content/` and `eval/` starts tagged. A native speaker clears one by
correcting the string and deleting its tag. Until this reaches 0, **no
patient-facing string in this repo is verified**, and nobody should say
otherwise on stage. `docs/02` §11 lists "native-speaker review slips" as a
tracked risk; this command is how you see it slipping.

**Step 1 — run the 60 sentences and the 10 prescriptions through the live app.**

```bash
python eval/score.py review-sheet -o eval/review_sheet.csv
```

Hands you a CSV, one row per sentence, with the hard case, the facts that must
survive (`must_keep`) and the inventions that must not appear (`must_not_say`).
A native speaker fills in `meaning_kept_yes_no` and `critical_error_yes_no`.

This harness **will not score translation accuracy itself**. `docs/01` §7 says
a native speaker on the team scores meaning-kept yes/no, and a model grading
its own translation is not a measurement. With no filled sheet, the number
reports as `NOT MEASURED` — never as an estimate.

**Step 2 — point the harness at the real log.**

```bash
python eval/score.py all \
  --log build/livekit/dev.log \
  --runs eval/runs.json \
  --sheet eval/review_sheet.csv
```

`unmute dev` writes `build/livekit/dev.log`; `--log` defaults to the sample
fixture so the harness runs before anything else exists. `runs.json` maps each
LiveKit `session_id` to the `eval/prescriptions.csv` row it was a run of —
write it as you do the runs (`eval/fixtures/runs.json` shows the shape).

---

## Which number answers which judge question

From the Q&A table in `docs/01` §9:

| Judge asks | Command | The number |
|---|---|---|
| **"What if the AI gets it wrong?"** | `score.py verbatim` | *N* of the 30 prescription runs (10 rows x 3 languages) spoken exactly as the template rendered them, and *N* of the 33 confirmed `RxLine`s (11 lines x 3 languages; row `rx-08` dictates two) reaching the patient verbatim inside them. This is the evidence behind the project's central safety claim, and the one number worth rehearsing. |
| …the same question, second half | `score.py teachback` | 5/5 seeded wrong read-backs caught, plus a control case that must **not** flag. A comparator that flags everything would also score 5/5, which is why the control is there. |
| **"Why not Google Translate?"** | `score.py score` | meaning-kept % per language, scored by a native speaker, over 20 sentences that deliberately include code-mixing, negations, lay terms and vague time. Plus: zero critical errors. |
| **"Isn't this a liability risk?"** | `score.py score` → critical errors | Any wrong drug, dose, timing or flipped negation. The target is zero *reaching the patient*; each one that occurred must be shown to have stopped at the confirm gate. |
| **"How fast is it?"** (docs/01 §7 row 1) | `score.py latency` | median, p90 and worst reply latency from the `"kind":"measurement"` records, against LiveKit's own bands (green ≤ 900 ms, slow > 900 ms, over limit > 1200 ms) rather than targets we invented. |
| **"Does the emergency detection work?"** | `score.py redflags` | How the keyword layer behaves over all 60 sentences. **Answer this one carefully** — see the warning below. |

### The red-flag answer, in the words to use

`content/redflags/*` is **not clinically reviewed**. No doctor and no hospital
department has signed it off; `docs/01` §5 lists a department-reviewed list as
explicitly later work. `score.py redflags` measures only whether the matcher
does what the file says — never whether the file is clinically right.

Say: *"a keyword tripwire that puts the patient's own words in front of the
doctor, plus an LLM confirming layer. The phrase list is ours, not a
department's — a clinically reviewed list per department is on the later
slide."* Do not say validated, approved, or screened. Overstating this would be
the worst error this project could make, and it is the kind of claim a judge
with a clinical background will test.

The most load-bearing part of that check is what **doesn't** fire: the 12
negation sentences ("I do *not* have chest pain") must raise nothing. A flipped
negation is named as a critical error in `docs/01` §6, and it bites the
keyword layer as hard as it bites translation.

---

## What is in here

| path | what it is |
|---|---|
| `sentences/{ta,kn,hi}.csv` | 20 patient sentences per language. Columns documented in `sentences/README-columns.md`. Deliberately loaded with code-mixing, negation, lay terms, sound-alike numbers, dosing shorthand and vague time. |
| `prescriptions.csv` | 10 dictated prescriptions with the exact expected `RxLine` structure (docs/04 §2), so a run can be diffed field by field. |
| `score.py` | the harness. Subcommands: `all`, `content-check`, `verbatim`, `teachback`, `redflags`, `latency`, `review-sheet`, `score`, `review-status`. |
| `readback_render.py` | a **second, independent** implementation of the read-back render, so `verbatim` has an expected string that does not come from the console grading itself. Also an executable spec of the contract at the top of `content/readback/ta.yaml`. |
| `fixtures/` | the synthesized `dev.log`, its `runs.json`, teach-back cases, half-step cases, a sample filled review sheet. See `fixtures/README.md`. |
| `devlog.py` | the dev.log reader, written against the generated emitter (docs/03 §14): sentinel-prefixed lines, records nested under their own `kind`, values in seconds, deduped by `(call_id, kind, id)` at the highest revision, `unavailable` records skipped. |
| `dose_words.py` | spoken dose to number — "half" is 0.5 and never 0. Reads each language's own count words out of `content/readback/*.yaml` so the words we say and the words we understand cannot drift apart. |
| `make_dev_log_fixture.py` | regenerates `fixtures/dev.log` and `fixtures/runs.json` from the real content. |

### Why the fixture deliberately fails some checks

`fixtures/dev.log` seeds two deviations on purpose. A fixture where everything
passes proves only that the harness prints "pass".

* **`rx-07`, all three languages** — the agent paraphrases the notes clause
  instead of reading it verbatim. `notes` is the one free-text field in the
  sentence, so it is the one an LLM is most tempted to reword.
* **`rx-01` in Tamil** — the same sentence in NFD with a doubled space.
  Byte-different, meaning-identical: it is the only thing that exercises the
  difference between the strict and the normalised count.

Expected result on the fixture: **26/30 byte-identical, 27/30 after NFC, 3
deviations reported, 30/33 lines verbatim, exit 0** — docs/02 §1.4 says to
report deviation honestly, not to hide it behind a pass.

### Two commands that are not about the demo numbers

```bash
python3 -I eval/score.py fixture-drift   # fixtures vs the real content files
python3 -I eval/score.py halfstep        # the half-step safety suite
```

**`fixture-drift`** is the answer to docs/00 §6's most expensive mistake: a
stale fixture copy of the content produced a "1.5 doses have no word"
diagnosis that was wrong in both directions and cost two round trips. Two
defences, both checked by this command — eval keeps **no copy** of the content
(`readback_render.py` reads `content/` directly), and `fixtures/dev.log`, the
one fixture that embeds rendered strings, is a **derived artifact**: the
command regenerates it in memory and fails loudly if the committed copy has
drifted, naming the line and the command to re-run.

**`halfstep`** is the answer to docs/00 §7. The same safety bug appeared in two
layers the day `Schedule` became multiples of 0.5 — `int()` truncation in the
comparator, and the word "half" parsed as 0 in the extractor — and *neither
would ever fire on a whole-number test case*. So this suite is all half-steps,
in all three languages, and it ends by re-running every case through both
broken implementations. **If either broken comparator passes the suite, the
command fails**, because a suite a known bug can survive is not a suite.

## Known contract gaps, found while writing this

Raised here rather than patched, because `docs/04` is the main session's file
and five sessions have coded against it.

1. ~~**A half dose cannot be expressed.**~~ **RESOLVED 2026-10-17** —
   `docs/04` §2 changed `Schedule` from `int` to multiples of 0.5 in 0–4.
   `rx-09` now encodes the half in the schedule itself (`morning: 0.5`, empty
   notes) and the read-back speaks it. All three templates carry the full
   half-step count table; Hindi's are suppletive (डेढ़, ढाई, साढ़े तीन) and must
   never be built by concatenation. A 0.5 rounded to 1 anywhere downstream is
   double the dose and a critical error — worth a test on both sides.
2. **Frequencies other than per-day cannot be expressed.** *(still open)* `schedule` is
   per-day only, so "one weekly" (row `rx-07`) has no home either. Silently
   rendering it as one a day is seven times the intended dose. The workaround
   is the same: notes plus an entry in `ambiguities[]`.
3. **`duration_days` cannot say "continue indefinitely".** *(still open)* `null` currently
   means "not stated", which is a different thing from "ongoing". The render
   omits the duration clause for `null` rather than inventing "as long as
   needed", which is the safe behaviour, but the two cases are not
   distinguishable.

## Notes for the sessions that load these files

* `console/app/readback.py` should implement the render contract written at the
  top of `content/readback/ta.yaml` — the same contract for all three
  languages. `eval/readback_render.py` is a working reference, and the
  `examples:` block at the bottom of each template file is a ready-made set of
  assertions for `console/tests/test_readback_templates.py` (18 cases, all
  passing against the reference).
* Hindi is the one language that needs grammatical gender: the sentence-final
  verb and the word for "half" both agree with the form noun, so
  `content/readback/hi.yaml` carries `gender` on each entry in `form_nouns` and
  the renderer must look it up rather than conjugate anything itself.
* `console/tests/test_teachback.py` should run `fixtures/teachback_cases.json`
  through `console/app/teachback.py`. If it disagrees with `score.py teachback`,
  the number on the slide came from the wrong implementation.
* The layer-1 matching rules for red flags — case-insensitive NFC substring,
  whole-phrase negation guards, longest match wins — are written once at the
  top of `content/redflags/en.yaml` and implemented in `score.py`'s
  `match_red_flags`. Hindi is where longest-match matters: `"ख़ून बंद नहीं हो रहा"`
  is a positive finding and `"ख़ून नहीं"` is a denial, and a naive matcher
  collides them.
