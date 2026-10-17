# content/ — the language files

Owned by the `content-eval` session (docs/04 §0). `console/` loads
`readback/` and `teachback` content; the unmute agent prompts inject
`glossary/`; the console's red-flag layer matches `redflags/`.

| directory | what it is | loaded by |
|---|---|---|
| `readback/{ta,kn,hi}.yaml` | the slot templates that turn confirmed integers and enums into the sentence the patient hears. No model in the loop. | `console/app/readback.py` |
| `glossary/{ta,kn,hi}.yaml` | lay-term pairs: few-shot pairs for the interpreter prompt, and the quoted term the doctor sees | agent prompts, console `Turn.lay_terms` |
| `redflags/{ta,kn,hi,en}.yaml` | danger-sign phrases matched against partial transcripts | console red-flag layer |

## Two separate kinds of "not reviewed"

**1. Linguistic.** Every patient-facing string here is DRAFTED by a non-native
speaker and carries a `NEEDS-NATIVE-REVIEW` tag. A native speaker on the team
clears one by correcting the string and deleting its tag.

```bash
python eval/score.py review-status      # how many are left
grep -rn NEEDS-NATIVE-REVIEW content/   # which ones
```

Reviewers should work from the rendered sentence, not the template: render the
cases in `eval/fixtures/` and read them **aloud**. The test is whether a
patient who left school before Class 10 follows it the first time. The anchor
study's health workers abandoned Google Translate because its output came out
transliterated or over-formal; a string that reads like a prescription label
has failed even if every word is correct.

**2. Clinical.** `redflags/` is **not clinically reviewed** and a native
speaker clearing its language tags does not change that. No doctor and no
hospital department has signed it off. docs/01 §5 keeps a department-reviewed
list as explicitly later work. It must never be described as validated,
approved or screened.

## The one structural thing to know

The read-back render contract — the exact steps that turn an `RxLine` into a
sentence — is written once, at the top of `readback/ta.yaml`, and is the same
for all three languages. `eval/readback_render.py` implements it; the
`examples:` block at the bottom of each file is the assertion set.

Where the three languages diverge from what an English template would suggest
(verb position, pluralisation, Hindi gender agreement, the fact that a `0` slot
is silent rather than spoken as "zero") is documented in each file, next to the
strings it affects.
