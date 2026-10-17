# Clinic Console

The FastAPI service that owns the screen's state, the doctor's confirmation gate, and every piece
of arithmetic a language model must not be trusted with. **unmute owns the conversation; the
console owns the clinical record.**

Implements `docs/04-interfaces.md` §3 (the agent's tool API), §4 (the browser API), §5 (the
WebSocket), §6 (the state mapping) and §7 (mock mode). Binds `127.0.0.1:8808` only.

## Run it

```bash
cd console
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

Pinned for this machine's **python 3.14.2** (no `uv`, no brew python here): fastapi 0.143.3,
uvicorn 0.54.0, pydantic 2.14.1, PyYAML 6.0.3, qrcode 8.2, pytest 9.1.1, httpx 0.28.1. All have
3.14 wheels, so nothing compiles. `requirements.txt` is runtime only.

Real mode — the agent and the browser both talk to it:

```bash
.venv/bin/python -m app.main
```

Mock mode (docs/04 §7) — replays a canned Tamil consultation over the WebSocket so `web/` can
build with no agent running. The gate is **real** in mock mode: the replay parks at
`await_confirm` until the doctor taps confirm-all in the browser.

```bash
.venv/bin/python -m app.main --mock
```

For an unattended replay (demos, CI), tap the gate automatically after N seconds:

```bash
.venv/bin/python -m app.main --mock --auto-confirm 3
```

Other flags: `--port`, `--reload`. `python -m app.main --help` lists them.

Mock and real differ **only inside the server**. The replay drives the same handlers as the
agent's tool calls, so every frame the browser receives is produced by the real implementation and
`web/lib/console-ws.ts` needs no `if (mock)` branch.

## Tests

```bash
.venv/bin/python -m pytest
```

| File | What it proves |
|---|---|
| `tests/test_gate.py` | The four invariants of docs/04 §3.1 — see below |
| `tests/test_teachback.py` | Five deliberately-wrong read-backs all produce mismatches, and content-eval's control case does not |
| `tests/test_readback_templates.py` | All 18 of the `examples:` cases in content-eval's template files render byte-exactly, plus the contract's structural rules (silent 0 slots, first-clause-only food relation, one sentence-final verb, count words not digits, Hindi gender agreement) |
| `tests/test_contract.py` | `RxLine` in `vaidyavaani-agent/state.py` matches docs/04 §2 field for field and constraint for constraint. **Skips with a reason** until that file exists; fails loudly on drift |
| `tests/test_api_surface.py` | Every §3/§4 endpoint and every §5 frame, by shape |
| `tests/test_mock_mode.py` | `--mock` replays a full consultation end to end |
| `tests/test_state_validation.py` | Hallucinated doses are rejected at the type boundary |
| `tests/test_privacy.py`, `test_metrics.py`, `test_cost.py` | Purge/TTL/one-time serve, dev.log parsing, ₹ arithmetic |

## Environment

| Variable | Default | Notes |
|---|---|---|
| `CONSOLE_TOKEN` | `dev-console-token` | `X-Console-Token` on every `/api/tools/*` call and on the gate. The agent must send the same value |
| `CONSOLE_PORT` | `8808` | |
| `CONSOLE_PUBLIC_URL` | `http://127.0.0.1:8808` | Base URL encoded in the take-home QR — set it to the tunnel |
| `CONSOLE_CONTENT_DIR` | `<repo>/content` | Holds `readback/{ta,kn,hi}.yaml` |
| `CONSOLE_DEV_LOG` | `<repo>/build/livekit/dev.log` | Where unmute writes measurements |
| `CONSOLE_DEMAND_LOG` | `console/demand_log.jsonl` | The only file the console writes |
| `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | `ws://127.0.0.1:7880`, `devkey`, `secret` | Token mint only; the console is never in the media path |
| `LIVEKIT_AGENT_NAME` | `vaidyavaani-livekit` | The name the compiled worker registers under. The join token dispatches it by name — see below |
| `CONSOLE_SESSION_IDLE_SECONDS` | `600` | Idle purge threshold |
| `CONSOLE_SWEEP_INTERVAL` | `60` | How often the sweeper runs |
| `CONSOLE_DISCONNECT_GRACE` | `30` | Purge delay after the last browser WS drops |
| `CONSOLE_VOICE_NOTE_TTL` | `1800` | 30 minutes |
| `CONSOLE_MOCK`, `CONSOLE_MOCK_AUTO_CONFIRM`, `CONSOLE_MOCK_SCRIPT` | — | `--mock` equivalents |

## The gate (docs/04 §3.1)

`GET /api/sessions/{id}/confirmation` long-polls for up to 25 s, returns `{"status":"pending"}` at
timeout, and wakes the instant the doctor acts. The four invariants, each proved in
`tests/test_gate.py`:

1. `confirmed` **only** when every line in `prescription.lines` has `confirmed: true`.
2. `readback_text` appears on a `confirmed` response and nowhere else.
3. `readback_text` is produced **only** by `app/readback.py` from confirmed `RxLine` fields.
4. The status vocabulary is exactly `pending | confirmed | rejected` — the same three strings as
   the tool's output `enum:`, which unmute checks at compile time.

`POST /api/sessions/{id}/rx/confirm-all` is the doctor's tap. It **does not confirm lines**: it
returns `409` while any line is unconfirmed, so the per-line taps have to happen first. Editing a
line afterwards clears `confirmed`, drops `readback_text` and puts the gate back to `pending`.

### Why the strength is never spoken — a deliberate choice, not an omission

The read-back says *how many and when*, never the milligram figure: "one tablet in the morning
after food, one at night, for 5 days" is the brief's own model sentence, and the render contract
has no slot for strength. For a patient who cannot read, the actionable unit is the count and the
time; a milligram figure adds load and nothing they can act on.

The strength is not lost — it stays on the doctor's card, the picture card and the printed slip,
where it is confirmed and checkable. Ruled on by the main session (docs/04 §2, "Rulings on the
read-back gaps console-backend raised").

### What may reach the spoken read-back

Inputs are the confirmed line's `schedule`, `form`, `food_relation` and `duration_days` — integers
and enums — plus `notes` (read verbatim, docs/01 §4) and, for a multi-drug prescription,
`drug_text`. Nothing from a transcript, a model, a tool body or a WS frame is an input.

`drug_text` and `notes` are the two fields whose characters came from the consultation. Both are
fields of the prescription the doctor read on screen and tapped, neither is ever normalised or
translated, and braces and newlines are stripped from both so neither can carry sentence structure
into the output. Editing a line to add a note clears `confirmed` and drops the rendered text, so
nothing unconfirmed can be spoken. All of this is tested in `test_gate.py`.

Honest limit, worth saying out loud on stage: the console renders the text, but in a cascade agent
the final audio still passes through the LLM's mouth. That is verbatim-read-with-verification, not
a byte-level guarantee — `eval/score.py` is what closes the gap, by diffing the spoken text in
`dev.log` against this render.

## Read-back template format

Small snapshots of content-eval's three files (at their commit 6485550) live in
`tests/fixtures/content/readback/` so the console runs and its tests pass before their branch
merges; the real `content/` takes over automatically and the same tests then run against it. If
`content/` is missing templates the console falls back to the fixtures with a warning on every
boot, and if neither exists startup fails with a clear message instead of crashing at the gate.

`content/readback/{ta,kn,hi}.yaml`, owned by the content-eval session. **The render contract is
the comment block at the top of `content/readback/ta.yaml`** and is identical for all three
languages; `app/readback.py` implements exactly that, lifted from content-eval's
`eval/readback_render.py` reference.

The two copies stay separate on purpose: `eval/score.py` diffs the **spoken** text against an
independently derived expected string, so if the console produced both sides it would be grading
itself. Don't make either one import the other, and treat any behaviour change here as a change
to the contract.

Per confirmed line, in order:

1. one clause per **non-zero** schedule slot — a 0 slot is silent, never "zero in the morning";
2. `food_relation` and the form noun appear on the **first clause only** (the brief's model
   sentence is "one tablet in the morning after food, one at night, for 5 days");
3. the duration phrase, then **one** sentence-final verb — all three languages are SOV, so the
   verb comes once at the very end, after the duration, not inside each clause;
4. `notes`, read back verbatim behind `notes_prefix` (docs/01 §4: free text, read back verbatim —
   the doctor owns the wording).

**Half doses** (docs/04 §2, changed 2026-10-17): `Schedule` values are numbers in multiples of
0.5 from 0 to 4 — `1`, `0.5` and `1.5` are legal, `0.25` and `1.3` are rejected at the type
boundary. `count_words` is keyed **by value** and covers every legal dose, and the lookup is by
`float`, never `str(n)`: Tamil and Kannada fuse a half into one word (ஒன்றரை, ಒಂದೂವರೆ) and Hindi
is suppletive (डेढ़, ढाई, and only from 3.5 the regular साढ़े तीन), so no dose word may be composed
from smaller ones. Only Hindi's `0.5` is gender-keyed, agreeing with the form noun: आधी गोली
against आधा कैप्सूल.

A whole dose stays an `int` on the wire, so the JSON is `{"morning": 1, "night": 0.5}` as docs/04
§2 shows — the agent types these as `float`, so a line arriving from a tool call carries `1.0` and
the console normalises it on the way in rather than letting a card read "1.0 tablet".

If a language file has no word for some dose, the loader **warns** at boot and the render blocks
that one line at the gate with a doctor-facing English message. Startup does not fail, and no word
is ever invented.

Two traps, both tested: `count` is a **lookup in `count_words`**, never `str(n)` (Tamil's ஒரு is
the only form allowed before a noun, so "ஒன்று மாத்திரை" is ungrammatical); and Hindi's
`form_nouns` entries carry a `gender` that the verb and the word for "half" agree with — the
renderer looks it up and conjugates nothing itself.

A line with **0 in every slot raises**: the patient hears nothing and the doctor gets
`errors.all_zero_schedule` in English. Same for an unknown form and an out-of-range duration.

Each language file's `examples:` block is the authority on the output — 18 cases across the three
languages, each with the input RxLine and the exact expected sentence, including one per language
that must raise. `tests/test_readback_templates.py` runs all 18 against the fixture snapshot and
again against the real `content/` once it lands. All 18 pass.

**Several lines is this console's layer, not the per-line contract.** Sentences are joined with
`joiners.line` (default `" "`), and when a prescription has more than one line each sentence is
prefixed with its `drug_text` via `templates.multi_line_prefix` (default `"{drug_text}: "`) so a
patient can tell two medicines apart. A single-line read-back names no drug, exactly like the
`examples:` cases and the brief's model sentence. Set `multi_line_prefix: ""` to turn the naming
off. Flagged to the main session as a contract gap, along with the fact that **strength is not
spoken at all** — the contract has no slot for it.

**Every string in those files is still tagged NEEDS-NATIVE-REVIEW.** The loader warns on every
boot for any language whose `review.status` is not `signed_off`, `/healthz` reports
`readback_review` per language, and `python eval/score.py review-status` counts the open tags.
That warning is meant to stay on until a native speaker has signed each file off.

## Empty strings from the agent

unmute builds every tool call **by keyword, every time**, so an optional tool input is always
supplied — as `""` when the model omits it (docs/04 §3). `app/models.py`'s `BlankAsAbsent` mixin
coerces `""` to `None` on every nullable field as the payload enters, so an omitted `notes` is
stored as `null` and an omitted optional enum does not fail validation. `ToolBody` and `RxLine`
both use it; `tests/test_api_surface.py` sends a line with every optional field as `""` and
asserts each one lands as null. This is the kind of thing that only shows up on a live call, which
is why it is tested rather than assumed.

## Teach-back

`POST /api/tools/teachback` takes `{patient_text, english_text}` and returns `TeachBackResult`.
A model supplies only *what the patient said* — optionally as `patient_said` values; if it is
absent, `app/teachback.py` extracts the numbers itself with a deterministic regex parser. Either
way **every verdict is computed in Python**, and numbers are compared arithmetically. With several
lines, the read-back is split at each drug name and each segment is compared against its own line.

`patient_said` is accepted in both shapes — flat slot keys
(`{"morning": 1, "night": 1, "duration_days": 2}`, as `eval/fixtures/teachback_cases.json` uses)
or nested under `schedule` (as docs/04 §2's example shows). Neither carries a verdict.

Doses are compared as numbers, never through `int()`: `int(0.5) == int(0)`, so an int-based
comparator scores a patient who repeats "one tablet" for a prescribed half as a **match** — the
double-dose miss teach-back exists to catch. The same applies to extraction, where `"half"` parses
to `0.5` and "one and a half" to `1.5`; mapping `"half"` to 0 would hide the same error.

`tests/test_teachback.py` runs content-eval's five seeded wrong read-backs **plus their CONTROL
case, which must not flag** — if the control flags, the comparator over-flags and the 5/5 catch
number is worthless. Their `tb-5` prescribes `morning: 0.5` against a patient who says 1, so an
int-based implementation fails it. All six pass.

## Mock script format

`tests/fixtures/consultation.json` — format owned by console-backend, clinical content by
content-eval.

```jsonc
{ "patient_language": "ta",
  "steps": [ { "after_ms": 400, "op": "turn", "turn": { /* Turn */ } } ] }
```

ops: `stage`, `partial`, `turn`, `consent`, `lang_detected`, `red_flag`, `rx_draft`,
`await_confirm` (blocks for the doctor's tap), `teachback`, `voice_note`, `metric`, `failover`,
`error`, `end`.

## Cost — ₹ per consultation

`GET /api/cost?minutes=10[&mode=demo|production][&session_id=…]`. Rates are USD per minute from
P0 (docs/02 §7.1), converted with one dated `USD_INR` constant rather than an exchange rate baked
into the arithmetic. Three things the endpoint is careful about, because each is a way to publish
a wrong number:

* **Audio seconds, not wall-clock.** STT and TTS are billed per minute of *audio*. A 10-minute
  consultation is mostly silence, so wall-clock badly overestimates TTS — at $0.0210/min the
  largest line by about 3×. `metrics.audio_seconds()` sums the measured **speaking** seconds
  (`speech_duration`) out of `dev.log`. Listening seconds are not in the log at all — the only STT
  measurement is a request duration and streaming STT never reports one (docs/03 §14) — so that
  line falls back to a stated fraction of wall-clock. Each line carries its own provenance
  (`tts_audio_seconds_source`, `stt_audio_seconds_source`, each `measured`, `supplied` or
  `assumed_from_wall_clock`), so the answer to "how was this derived?" is never a guess dressed
  as a measurement.
* **Demo cost ≠ production cost.** The platform bundle is $0.003 per agent-minute and genuinely
  $0 on a local LiveKit server, so `mode` picks one and the response carries
  `platform_bundle_charged`.
* **The LLM line is excluded, not estimated.** The Context Router is BYOK: the provider bill is
  ours and SLNG publishes no markup, so `breakdown.llm.usd` is `null` with `placeholder: true`
  and `excludes_llm: true`. An invented figure would be worse than an absent one.

`rate_notes` carries the one disagreement P0 found rather than resolving it silently: soniox
rt-v5 is $0.0038 in the catalog and $0.0028 in the docs; the catalog figure is used.

## Fixtures — why there is no copy of anyone else's content here

`console/tests/` holds no snapshot of `content/` or `eval/fixtures/`. Tests read those files from
where their owner keeps them, and skip with a reason if they are absent. There was a snapshot
early on, to run before content-eval's branch landed, and it did exactly what a second copy does:
it went stale, and a failure it manufactured cost two sessions a round trip. The only fixtures
left under `tests/fixtures/` are things this session owns — `consultation.json` (the mock script)
and `dev.log.sample` (unmute's log shapes, lifted from docs/03 §14 — see the fixture README).

## The join token also dispatches the agent

`mint_join_token` puts a `roomConfig` claim — `{"agents": [{"agentName": LIVEKIT_AGENT_NAME}]}` —
next to the `video` grant, and asks for `roomCreate` so the join that creates the room is allowed
to configure it. Without it the worker never joins: the generated package registers with an
explicit agent name (`build/livekit/agent.py`, `@server.rtc_session(agent_name="vaidyavaani-livekit")`),
and LiveKit excludes a named worker from automatic dispatch, so the room gets the default
empty-name dispatch, which matches nothing.

Nothing errors when that happens. The token parses, the room exists, the browser connects and
publishes — the patient speaks and nothing is listening. That is the whole symptom, which is why
this is a token claim with a test on it rather than a comment.

Verified against a running stack, not only in a unit test: with the claim, LiveKit creates a
dispatch for `vaidyavaani-livekit` and the worker joins the room within about four seconds
(`agent-AJ_…` appears as a second participant). The name lives in `config.LIVEKIT_AGENT_NAME`
alone, defaulted from the compiled worker and env-overridable, so the two cannot drift.

## Privacy posture

No database. Nothing persisted but `demand_log.jsonl` (requested language + a note; no
identifiers, no transcript, no audio). Sessions live in memory and purge on `end`, after the
browser WS drops (grace, then the sweeper), and when idle. Voice-note WAVs live in memory with a
30-minute TTL and are served exactly once — the second `GET /api/voicenote/{token}` is a 404 by
design. Bound to loopback only.

## Known gaps

* **Five tests are red against the tree as merged, and all five close on the next merge.** Both
  groups are cross-session contract gaps that the tests exist to catch, so none of them should be
  silenced:
  * `test_contract.py` ×2 — `vaidyavaani-agent/state.py` in this tree still declares
    `morning: int = Field(0, ge=0, le=4)`, so a half dose validates here and is rejected there.
    unmute-agent fixed it on their branch.
  * `test_readback_templates.py::test_every_legal_dose_has_a_word` ×3 — `content/readback/*.yaml`
    in this tree has no word for 1.5, 2.5 or 3.5, so a doctor prescribing one is blocked at the
    gate. content-eval fixed it on their branch. Eight dependent cases skip with a message
    pointing at this one, so the suite shows one root cause rather than nine failures.

  Verified: with content-eval's and unmute-agent's branch files in place, the suite is
  **249 passed, 0 failed, 0 skipped**.

* **The LLM line in `cost.py` is excluded from the total**, because the router is BYOK and there
  is no published markup to model. Every other rate is real (docs/02 §7.1).
* `metrics.py` now parses the **confirmed** record shapes, read off the generated emitter
  `build/livekit/utils/dev_metrics.py` and documented in `docs/03-p0-findings.md` §14 — nesting
  under the `kind` key, seconds not milliseconds, `state: "unavailable"` records with no `value`,
  revision dedupe, and `first_response` disambiguated by `source`. What is still unconfirmed is
  *which* records a real VaidyaVaani turn emits and in what order: no live turn has run, and
  `tests/fixtures/dev.log.sample` is §14's synthesized sample, so **no timing in it is measured**.
  Two things outside `console/` the HUD depends on: `UNMUTE_DEV_METRICS` must be set in the
  worker's environment or nothing is emitted at all, and `speech_duration`'s `source` string is
  not recorded anywhere, so the cost path matches that metric by name alone.
* The console does not synthesise the take-home WAV. It stores `audio_b64` if the caller sends it;
  otherwise it keeps a short silent placeholder so the QR path is demonstrable.
