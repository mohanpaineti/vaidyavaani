# Column contract for eval/sentences/{ta,kn,hi}.csv

Each file holds 20 symptom sentences as a patient would really say them.
`eval/score.py` reads these and emits the native-speaker review sheet.
Every row's `sentence` is **DRAFTED, NOT VERIFIED** — the `review` column
carries `NEEDS-NATIVE-REVIEW` until a native speaker clears it.

| column | meaning |
|---|---|
| `id` | stable id, `<lang>-NN`. Never renumber — the review sheet joins on it. |
| `sentence` | what the patient says, in script. This is what gets spoken into the mic. |
| `roman` | romanisation, so a non-reader of the script can still run the test |
| `expected_english` | the intended meaning. The *meaning* is the assertion, not the wording. |
| `hard_case` | why this row exists: `code_mix`, `negation`, `lay_term`, `sound_alike_number`, `dosing_shorthand`, `vague_time`, `folk_concept`, `ambiguous`, `plain` |
| `must_keep` | `;`-separated facts the English MUST contain. Checked by a human on the sheet; a missing one is a MEANING FAILURE. |
| `must_not_say` | `;`-separated things the English must NOT contain (inventions, flipped negations). Any hit is a **critical error**. |
| `expect_red_flag` | expected flag id from `content/redflags/`, or empty. `none` means a flag here would be a false positive. |
| `review` | `NEEDS-NATIVE-REVIEW` until a native speaker signs the sentence off |

**Negation rows are the sharp end.** docs/01 §6 names a flipped negation as a
critical error, and docs/02 §10 asks for negated sentences per language. A row
whose `must_not_say` is violated counts as a critical error in `score.py`, and
critical errors must be **zero** past the gate.
