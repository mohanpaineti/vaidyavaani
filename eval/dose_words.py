"""Turning a spoken dose back into a number — eval's own implementation.

`console/app/teachback.py` has one of these too, and that is deliberate: if the
two disagree, one of us has misread the contract and we want to know before a
patient's teach-back is scored by it.

**Why this file exists at all.** docs/00 §7 records the same safety bug found in
two layers on the day `Schedule` changed from `int` to multiples of 0.5:

* the comparator truncated with `int()`, so a prescribed **half** against a
  patient who heard **one** scored as a MATCH — a double dose, recorded as
  understood;
* the extractor mapped the word `"half"` to **0**, so a prescribed **zero**
  against a patient saying **"half"** also scored as a MATCH.

Both are silent failures inside the exact mechanism built to catch
misunderstanding, and **neither would ever fire on a whole-number test case.**
So: `"half"` is 0.5 here and nowhere near 0, every value stays a float, and
`eval/score.py halfstep` proves a suite that misses this cannot pass.

The patient's words reach us in two forms, and both are handled:

* **English**, because the interpreter translates before the comparator sees
  anything — "half a tablet", "one and a half";
* **the patient's own language**, read out of `content/readback/*.yaml`'s
  `count_words` so that the words we *say* and the words we *understand* can
  never drift apart. There is no second copy of the table to go stale.
"""

from __future__ import annotations

import re
import unicodedata

import readback_render as rr

# Longest first: "one and a half" must win over the bare "half" inside it.
# Each pattern is anchored to the whole phrase so that "half" in "half an hour"
# is not read as a dose by accident.
_ENGLISH_PATTERNS: list[tuple[str, float]] = [
    (r"(?:three|3)\s+and\s+(?:a\s+)?half", 3.5),
    (r"(?:two|2)\s+and\s+(?:a\s+)?half", 2.5),
    (r"(?:one|1|a|an)\s+and\s+(?:a\s+)?half", 1.5),
    (r"half\s+(?:a|an|one)\b.*", 0.5),
    (r"(?:a\s+)?half", 0.5),
    (r"four|4", 4.0),
    (r"three|3", 3.0),
    (r"two|2", 2.0),
    (r"one|1|a|an", 1.0),
    (r"zero|none|0", 0.0),
]


class DoseWordError(ValueError):
    """The words do not name a dose this contract can represent."""


def normalise(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", str(text)).lower().split())


def language_words(lang: str) -> dict[str, float]:
    """`count_words` from the real content file, inverted.

    Hindi's 0.5 is a gender pair (आधी / आधा) and both spellings must parse.
    Read live from `content/`, never copied — a drifted copy of this table is
    exactly how the "1.5 has no word" false diagnosis happened (docs/00 §6).
    """
    table: dict[str, float] = {}
    for key, word in rr.load(lang)["count_words"].items():
        value = float(key)
        forms = word.values() if isinstance(word, dict) else [word]
        for form in forms:
            table[normalise(form)] = value
    return table


def parse_count(text, lang: str | None = None) -> float:
    """A spoken or written count to a float dose. Raises rather than guessing.

    A number already parsed upstream passes straight through, so a case file may
    carry `0.5` or `"half"` and mean the same thing.
    """
    if isinstance(text, bool):
        raise DoseWordError(f"{text!r} is not a dose")
    if isinstance(text, (int, float)):
        return float(text)
    phrase = normalise(text)
    if not phrase:
        raise DoseWordError("empty dose phrase")

    if lang:
        word = language_words(lang).get(phrase)
        if word is not None:
            return word

    try:
        value = float(phrase)
    except ValueError:
        pass
    else:
        return value

    for pattern, value in _ENGLISH_PATTERNS:
        if re.fullmatch(pattern, phrase):
            return value

    raise DoseWordError(
        f"no dose value for {text!r}"
        + (f" in {lang}" if lang else "")
        + " — refusing to guess, because guessing 0 for a half is the §7 bug"
    )
