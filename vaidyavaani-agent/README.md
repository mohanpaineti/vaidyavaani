# vaidyavaani-agent — the unmute package

The conversation half of VaidyaVaani: a two-way voice interpreter for a
government hospital consultation in Bengaluru. Authored as YAML + Markdown and
compiled ahead of time to a LiveKit Python worker. unmute is a compiler, not a
runtime — it is never in the call path.

The clinical half lives in `console/`. The split is the whole design: **unmute
owns the conversation, the Clinic Console owns the clinical record.** Anything
that must be exactly right — a dose, a comparison, a template — is Python in the
console. Anything that must be natural — turn-taking, phrasing, asking again —
is in here.

Interface contract: [`docs/04-interfaces.md`](../docs/04-interfaces.md).
Design: [`docs/02-technical-architecture.md`](../docs/02-technical-architecture.md) §3.

## Status

| | |
|---|---|
| `unmute validate` | ✅ clean, **zero warnings**, against unmute 0.7.4 |
| `unmute compile --target livekit` | ✅ succeeds; `compile-report.json` carries 5 informational notes and no warnings |
| Seven local tools | ✅ present, output enums match `docs/04` §3 |
| `state.py` | ✅ matches `docs/04` §6 field for field; `RxLine` matches §2 field for field |
| `read_back` has `context: history: reset` | ✅ compiles to an empty `ChatContext` on entry |
| Model and voice ids | ✅ verified by P0 (`docs/03-p0-findings.md`) |
| Can it actually run? | ⚠️ **Everything but the LLM is ready.** See below |

Warnings exit 0 in unmute, so "clean" above means the output was read, not that
the exit code was trusted. `compile-report.json` has a `notes` array and no
warnings array populated; the notes are:

```
listen: slng via slng.STT (livekit-plugins-slng>=1.8.1, verified 2026-07-15)
reason: openai via openai.LLM (livekit-agents[openai], verified 2026-07-18)
speak:  slng via slng.TTS (livekit-plugins-slng>=1.8.1, verified 2026-07-15)
turn role lowers to LiveKit Inference turn detection; its binding placement is advisory
turn pace snappy (silence 0.25s authored, closes at 1.2s)
```

### One blocker left: the reasoning model

P0 is done. `docs/03-p0-findings.md` smoke-called every id, and all of the
speech ids are now verified values rather than placeholders — there is not a
single `⚠ VERIFY` marker left in `agent.yaml`. Three of `docs/02`'s guesses were
wrong, and the corrections are in place:

| Binding | Verified value | What changed |
|---|---|---|
| `models.listen.indic` | `sarvam/saaras:v3`, **no `language:`** | Saaras auto-detects and *ignores* a language hint, and **no code-mix parameter exists or is needed**. One entry really does serve the Tamil patient and the English doctor — `docs/02` §1.1 stands as written, and the per-language fallback §11 held in reserve is not needed |
| `models.listen.multi_backup` / `soniox_backup` | `deepgram/nova:3`, `soniox/speech-ai:rt-v5` | both confirmed reachable with `world_part: in`, but see residency below |
| `models.speak.bulbul_*` | `sarvam/bulbul:v3`, **voice `anand`** (bare name), `language: ta\|kn\|hi` | the scoped ids the catalog advertises are **rejected** by Sarvam (`ta-IN-anand` → "Speaker … is not recognized"), and there is no `hi-IN-*` voice at all. Only the 37 bare names work; `voice:` is required. `anand` covers all three languages plus English, verified by live synthesis |
| `models.turn.detector` | `turn-detector-mini` | `silero` is a compile error, as already found here |

**The LLM is the one thing still open, and it needed a design change.**
`docs/02` §0 lists the SLNG Context Router as a locked decision. It cannot be
used right now: `slng/auto` does not exist, and more importantly **the org has
no router configuration at all** — every model id tried against
`https://in.context-router.slng.ai/v1` returns HTTP 400 `no org config found
for org 2afc4597-…`. The endpoint is reachable and the key authenticates; there
is simply no mapping from model ids to upstreams, which is org-side
provisioning, not a YAML fix.

So **`think` is now bound to a direct provider** (`provider: openai`,
`gpt-5.6-terra`, `temperature: 0`, `reasoning_effort: "none"`), on
`setup-infra`'s recommendation that P1 should not be blocked waiting on
provisioning. The full router shape, with every required field, is kept as a
comment on that binding so switching back is a six-line edit once a direct curl
to the router returns 200.

**What that costs, stated plainly, because it touches the pitch and not just the
code:**

* the router's cache, and with it the per-agent cache scoping that would have
  kept the three language agents from serving each other's cached lines
* the "SLNG end-to-end" line on the architecture slide — speech is SLNG,
  thinking is not
* thinking now leaves India entirely

That last point is a decision for the main session, not for this package: it is
a change to a locked decision in `docs/02` §0, forced by provisioning rather
than chosen. **Nobody has confirmed the team has an OpenAI key either**, and
without one the agent still cannot think. `reasoning_effort: "none"` is
mandatory rather than optional, because every agent here has tools and the
gpt-5.6 family returns 400 on every tool turn without it.

### Residency is not uniform, and the slide must not say it is

P0 read the catalog's per-model `hosted_in`, not just the gateway:

| Model | `hosted_in` | `cross_region` | |
|---|---|---|---|
| `sarvam/saaras:v3` | `in` | false | ✅ stays in India |
| `sarvam/bulbul:v3` | `in` | false | ✅ stays in India |
| `deepgram/nova:3` | `au` | true | ❌ → Australia |
| `soniox/speech-ai:rt-v5` | `jp` | true | ❌ → Japan |

The two models carrying the consultation are genuinely India-hosted and
India-served. **The moment `listen.fallback` trips, audio leaves the country** —
and with a direct `think` binding, thinking does too. The failover beat and the
residency claim are therefore in direct tension. Say so: *"Saaras and Bulbul are
India-hosted and India-served, and we checked `hosted_in`, not just the gateway.
Our STT fallbacks are not — they route to Australia and Japan. We chose
availability over residency on the fallback path, deliberately, and here is the
flag that tells us when it happens."*

Two more claims in `docs/02` that need weakening before the slide:

* **Turn detection is not local.** `turn-detector-mini` lowers to
  `inference.TurnDetector(version="v1-mini")` — LiveKit Inference, i.e. cloud.
  The compile report says as much. Only the VAD is local silero. §1.3's "local
  silero" framing should not be used as a privacy point.
* **`endpointing_delay: 250ms` is a floor, not the delay.** It compiles to
  `endpointing={"mode": "dynamic", "min_delay": 0.25, "max_delay": 1.2}`. Quote
  250 ms as the floor and 1.2 s as the ceiling.

### Still untested, and worth knowing before the demo

* **Failover transcript quality on Indic audio.** Saaras's auto-detection is
  Saaras's own behaviour, not unmute's, and unmute cannot vary language
  mid-call. The two fallbacks are *not* known to auto-detect that way, and
  `deepgram/nova:3` is reported to need `language: multi` to be multilingual at
  all. So during the failover beat, **check the transcript, not just that audio
  kept flowing** — the call may survive and the Tamil may come back as noise.
* **Nobody has listened to the Bulbul audio.** Synthesis succeeded; accent and
  intelligibility across ta/kn/hi from one voice is a native-speaker call.

## Layout

```
agent.yaml          the whole declaration; unverified ids in one block at the top
targets.yaml        one target: livekit, deployment_region ap-south
state.py            Pydantic — the dose type system
instructions/
  greeter.md        the opener: find the language, hand off, nothing else
  interpreter.md    shared by all three language agents
tasks/              one prompt per step of the six-step flow
tools/              seven local tools, each a .yaml contract + a .py handler
.env.example        names only, never values
```

## How the safety gate is built

Nothing clinical is spoken to the patient until a human doctor taps confirm.
That is held up by four mechanisms, in order of strength:

**1. Pydantic validation at the point of entry.** `state.py` types a dose.
unmute validates every task `assign:` against the destination field *before*
anything is saved, and an invalid value leaves the task open so the model
corrects itself. Verified by hand against the real `state.py`: `morning: 10`,
`duration_days: 500`, `duration_days: 0`, `"one-ish"`, `food_relation:
"whenever"`, `strength_unit: "spoons"`, `strength_value: 99999`, a negative
strength, `form: "powder"` and a line with no `drug_text` are all rejected; so
is `patient_language: "te"`. A hallucinated dose cannot enter state at all, and
the agent asks the doctor again rather than proceeding with garbage.

`Schedule` takes **multiples of 0.5 from 0 to 4**, not integers (docs/04 §2,
changed 2026-10-17): half a tablet is one of the commonest doses in Indian
practice and is in the brief's own edge-case table, and under an `int` schedule
"half a tablet twice a day" made the agent re-ask mid-consultation. The bound is
`multiple_of=0.5`, which keeps it a quantised check rather than a bare float —
`0.5` and `1.5` are accepted, while `0.25`, `1.3`, `0.6666` and `1.0000001` are
each rejected with a `multiple_of` error. Anything finer than a half is not a
recordable dose, and `tasks/capture-prescription.md` tells the model to put it
in `ambiguities` for the doctor rather than approximate it to the nearest half.

**2. A compile-checked `finish:` gate.** `confirm_prescription` ends only when
`await_doctor_confirmation` returns `status: confirmed`. The console returns
`pending` until a human taps. `success:` values must appear in the tool's output
`enum:`, so a typo is a compile error rather than a gate that never closes. In
the generated worker this is literally
`if not _terminal_success(result, {"status": ("confirmed",)})`, and anything
else goes back to the model with the task still open — it cannot talk its way
past it.

**3. No path around it.** `read_back` is a step of the `consultation` task group
and, like every other consultation task, has **no `when:`** — unmute makes such
a task a definition that can only run as a group step, never attached by bare
name or triggered by the model. The group's `steps:` are a fixed order with the
gate before the read-back, and `read_back`'s prompt reads
`{{state.readback_text}}`, which only the gate task assigns. So there are three
independent reasons the read-back cannot be reached early, and the gate tool's
own handler returns `pending` on *every* failure path — an unreachable console,
an unparseable reply, or a `confirmed` with an empty `readback_text`. No error
in that file can open the gate.

**4. Template-rendered read-back, measured not asserted.** The console renders
the spoken sentence from the confirmed numbers and enums; the agent only reads
it. `read_back` has `context: history: reset`, which compiles to
`await self.update_chat_ctx(llm.ChatContext())` on entry — no earlier
conversation at all, not even the sentence that triggered the step, so there is
nothing to rephrase from and no patient question to be helpful about.

**Be honest about #4.** In a cascade agent the final text still passes through
the LLM's mouth, so this is **verbatim-read plus measurement, not a byte-level
guarantee**. `temperature: 0`, a reset context and a one-instruction prompt are
the strongest architectural levers available here, and they are not a proof.
`eval/score.py` closes the gap with evidence instead: it diffs the **spoken**
text in `build/livekit/dev.log` against the console's template render across all
10 prescription runs. If any run deviates, that gets reported rather than
hidden.

Two further safety choices beyond `docs/02`: `teach_back` and `take_home` also
end on their tools' results, so the teach-back verdict and the voice-note token
come from the console rather than from the model. (It also keeps the base64 QR
data URI out of the prompt, since a `finish:` tool's result never reaches the
model.)

## Deviations from docs/02, and why

These are the places unmute's actual schema would not accept what `docs/02`
sketched. **The doc is wrong on these points, not the package** — each was
found by running `unmute validate` against 0.7.4, and `docs/02` is owned by the
main session, so it needs updating there.

1. **`turn:` cannot be `model: silero` on LiveKit.** §1.3 wrote that. LiveKit
   checks the detector identity and refuses `silero`, which is a VAD and not a
   turn detector; only `turn-detector-mini` or `turn-detector` are accepted.
   Found independently here and in P0. Written as
   `provider: livekit, model: turn-detector-mini` — P0's §10 block writes
   `provider: local` for the same model and that compiles too; `livekit` is what
   `unmute init` scaffolds, so this package keeps it. **`pace: snappy` and
   `endpointing_delay: 250ms` survive unchanged**, so the design intent is
   intact. Two caveats on the claims this supports, both from P0: it lowers to
   LiveKit Inference (cloud, not local), and 250 ms is the floor against a
   1.2 s ceiling.

2. **The Context Router is not usable, so `think` is bound direct.** §3.1 wrote
   `provider: slng` with `model: slng/auto` and no other keys. Three separate
   problems, found here and then confirmed live by P0: a `provider: slng` think
   binding *is* the router and requires `agent_id` and `upstream` (it is a cache
   in front of *your* model, and your credentials travel with the request);
   `slng/auto` does not exist; and the org has **no router config at all**, so
   nothing resolves through it. See "One blocker left" above for what the direct
   binding costs. This also retires §12.4 as a question: the router was *not*
   "already provisioned for us".

3. **`fallback: [router_backup]` on `think` is dropped.** §3.1 named
   `router_backup` and never defined it, which is a build error on its own. A
   second router entry would also need its own verified upstream and must agree
   on `agent_id`. §12.4 lists "whether `fallback` on `think` is useful to us" as
   an open question, so this is deliberately deferred rather than guessed at.
   **STT fallback, the one the failover demo needs, is intact** and compiles to
   `stt.FallbackAdapter` over all three listen entries.

4. **`assign: prescription_confirmed: true` is refused.** An `assign:` value
   must be `result.<field>`; a literal is not a name. So the gate tool returns a
   `confirmed` boolean alongside `status`, and the flag is assigned from the
   console's own answer. This is strictly better: the flag now cannot be set by
   a constant written in the package.

5. **`{{glossary}}` is not expressible.** A double-brace placeholder may only
   name a field on `State`, and unmute has no include mechanism for a prompt
   file. The lay-term glossaries in `content/glossary/` are therefore a
   **build-time injection** at a marked point in `instructions/interpreter.md`,
   not a template variable. See "Dependencies" below.

6. **`speak:` cannot take `fallback:` on any target.** Confirmed — §5 already
   says so. TTS failover is a manual swap; say that honestly if a judge asks
   rather than implying the failover demo covers it.

7. **`secrets:` needs the upstream's key too.** `OPENAI_API_KEY` is in the
   compiled `required_env` because the router forwards upstream credentials. It
   changes name if P0 confirms a different upstream.

### Two shapes that need the main session to arbitrate

Both are places `docs/02` §3.2 and `docs/04` §2/§6 disagree with each other, not
places unmute objected. I picked the reading that keeps
`console/tests/test_contract.py` passing and flagged it rather than silently
choosing:

* **`RxLine` carries `id`, `confidence` and `confirmed`.** §3.2 omits all three;
  §2 includes them and §6 says the Pydantic model and the JSON shape "must match
  field for field". So they are declared here, defaulting to `None`/`False`, and
  documented as console-owned — the agent never sets them. The field list is now
  exactly §2's eleven, in §2's order.
* **`TeachBack` has only `overall` and `mismatched_fields`.** §3.2's shape. §2's
  `TeachBackResult` also has `per_line` and `simplest_restatement`, but §6 types
  the *state* field as `TeachBack`, and `per_line` is a console display shape
  with no consumer in the agent. `compare_teachback` does return
  `simplest_restatement` to the model for the repeat-the-mismatch step; it is
  just not stored in state.

### One choice that was not forced

`docs/02` §3.4 says shared tool helpers "must be copy-pasted per handler file".
That is true of `tools.shared`-style **imports** — the compiler reads only the
file named by `local.handler` and does not follow its imports. But unmute does
support one authored file serving as the handler for several tools. The `_post`
helper is copy-pasted into all seven handlers anyway, so each tool's contract
and its code sit together; if that duplication becomes a liability, the
supported fix is one shared authored file, not an import.

## Dependencies on other sessions

* **`setup-infra`** → `docs/03-p0-findings.md`. **Landed** (branch
  `claude/setup-infra-98f13c`); every speech id in `agent.yaml` now comes from
  it. What it leaves open for this package is the reasoning model: either an
  org-side router config, or confirmation that the team has a direct LLM key.
* **`console-backend`** → the seven endpoints in `docs/04` §3. The handlers
  target them exactly, and the gate expects
  `GET /api/sessions/{id}/confirmation` to long-poll ~25 s and to return
  `readback_text` **only** on a `confirmed` response.
* **`content-eval`** → `content/glossary/{ta,kn,hi}.yaml`, appended into
  `instructions/interpreter.md` at the marked point before compiling. Until that
  build step exists, the interpreter prompt falls back on the model's own
  knowledge of everyday illness words — which is exactly why the console also
  runs a keyword layer over partial transcripts that does not depend on it.
  `content/readback/{ta,kn,hi}.yaml` is the console's input, not this package's.

## Audited against the official Unmute skill

`unmute skill` was installed partway through this build, and the brief says to
prefer it over any notes. The package was re-read against
`.agents/skills/unmute/` and three things came out of it:

* **A latent bug in three handlers, now fixed.** *"An optional `input` property
  is always passed, as an empty string […] a Python default in your handler is
  dead code: it receives `""`, not `None`."* `push_turn`, `publish_draft_rx` and
  `log_unsupported_language` all had `=None` defaults. The `or []` / `or ""`
  idiom already handled `""` correctly by luck, but the signatures were
  misleading — someone "tidying" one into `if x is None:` would have broken it
  silently, and the skill is explicit that neither `validate` nor `compile`
  would say a word. Defaults are now `""`, with a comment saying why, and it is
  verified: passing `""` for `lay_terms`, `negations` and `ambiguities` puts
  `[]` in the payload, not an empty string.
* **YAML sequences are now block-style**, as the skill requires of
  assistant-authored packages. The conversion was checked by parsing before and
  after and asserting the loaded data was identical.
* **`provider: livekit` for `turn-detector-mini` is confirmed** — the skill's own
  example writes it that way. P0's §10 block writes `provider: local` for the
  same model and that also compiles; this package keeps `livekit`.

It also confirmed the gate's third guarantee in stronger words than the public
docs: *"A task with no `when:` is a definition only, valid solely as a step of a
task group. An agent naming it by bare name […] is refused."*

One tension worth naming, since it is the opposite of normal practice: the skill
lists *"no spoken example from the prompt comes back word for word"* as a thing
a good agent does, and *"asserting on strings gives you a test that fails on
every harmless rewrite"* as a reason not to test for it. The read-back step
deliberately wants exactly that echo. That is not a misreading of the guidance —
it is why the read-back is the one place we measure the spoken string rather
than trusting the prompt.

## The first live turn: `language:` is regioned, `voice:` is not

**The most expensive trap in the build, and it was sitting one line below the
one we had already caught.** `docs/00` §6 records *"Only the 37 bare names
work"* about `voice:`. True — and directly underneath it sat a `language:`
field where the bare form is **wrong**. Two fields, one line apart, opposite
conventions for the same language. Both validate green and compile green.

The first live turn ever attempted, on the greeter's opening sentence:

```
SLNG TTS error: Validation Error(s):
- config.data.target_language_code: Input should be 'bn-IN', 'en-IN', 'gu-IN',
  'hi-IN', 'kn-IN', 'ml-IN', 'mr-IN', 'od-IN', 'pa-IN', 'ta-IN' or 'te-IN'.
status_code=422, retryable=False
```

`retryable=False`, so the STT fallback chain does not absorb it and nothing
retries into success: with bare codes **every patient-facing utterance in all
three languages fails, every time**. The error enumerates the accepted set
itself, so that list is authoritative rather than inferred.

Fixed on all three `speak` entries: `ta` → `ta-IN`, `kn` → `kn-IN`,
`hi` → `hi-IN`. The three bare `language:` values were the **only** ones in the
package — the `listen` entries deliberately carry none (Saaras auto-detects),
and the handoffs carry only `to`, `when` and `context`.

**Do not propagate the regioned form.** Three spellings of the same idea coexist
on purpose, each right where it is:

| Where | Form | Why |
|---|---|---|
| `models.speak.*.language` | `ta-IN` | Bulbul's `target_language_code` |
| `state.patient_language` | `ta` | `docs/04` §6, asserted by `console/tests/test_contract.py` |
| `create_voice_note`'s `language` input | `ta` | the console keys `content/readback/{ta,kn,hi}.yaml` on it |

### English through an Indic language code

There is no fourth `speak` entry for English and there must not be. `speak` is
per-agent and `language` is fixed per entry — the skill is explicit that Unmute
exposes no binding that changes it during a call — so the English the
interpreter speaks **to the doctor** is synthesized through whichever of the
three entries its agent holds. `en-IN` is in the accepted set, but binding an
agent to it would synthesize the *patient's* own language under an English
code, and the patient is the one who cannot read the screen. The patient's
language wins each entry; English rides through it. The greeter's opener is the
most exposed case — `"ನಮಸ್ಕಾರ. Please hold your button and speak in your own
language."` is Kannada and English in one utterance through `kn-IN`, and it is
the first thing anyone hears. **Nobody has listened to it.**

### What the live run actually proves, and what it does not

Worker rebuilt from the fixed package and dispatched twice against the local
LiveKit server. The giveaway in the failing run was `"audio_chunks": 0` with
`first_audio_ms: null`; after the fix, on the greeter's `kn-IN` opener:

```
cold: outcome=completed audio_chunks=9  ws_connect_ms=3679.8 first_audio_ms=4736.8 audio_end_ms=6270.3
warm: outcome=completed audio_chunks=10 ws_connect_ms=761.1  first_audio_ms=1228.5 audio_end_ms=1631.9
      TTS metrics ttfb=0.467s audio_duration=3.6s
```

Zero `target_language_code` errors across both runs. **Audio is genuinely being
produced where before there was none.**

Three honest limits on that:

1. **Only `kn-IN` has been exercised end to end.** `ta-IN` and `hi-IN` are
   reached only by handoff, and a handoff needs a real patient utterance through
   STT, which has not happened. Seeding `patient_language` through the dispatch
   metadata does not get there: the greeter still waits to hear somebody. I also
   tried synthesizing each code straight at the gateway, which cleanly
   reproduced the **rejection** of all four bare cases but could not complete
   the gateway's own handshake on the regioned ones, so it proves the bug and
   not the fix. **`ta-IN` and `hi-IN` are therefore believed-correct, not
   demonstrated** — they are in the gateway's enumerated accepted set and travel
   the identical code path with only the string differing. That is reasoning,
   which is exactly the kind of thing this trap punished. A live Tamil utterance
   is what settles it.
2. **None of these timings is a latency number.** `first_audio_ms` is dominated
   by the TTS websocket connect (3.7 s cold, 0.76 s warm) to the India gateway
   on a first-ever connection in a fresh venv. The only figure resembling a
   latency measurement is `ttfb=0.467s` on the warm run, and it is one sample of
   one utterance with no caller in the room. Quote nothing from here.
3. **The first segment of the cold run failed separately** — a 10 s timeout with
   every timing `null` and no gateway request id, then a retry that succeeded.
   That is not the language bug (no 422, and the warm run is clean), but it is
   an unexplained cold-start fragility on the very first utterance of a worker,
   which is precisely when a demo starts. Worth watching.

## The trap audit, 2026-10-17

A second pass over this package, against the traps `docs/00-HANDOVER.md` §6 and
§12 record — the ones that cost real time to find and that only fire on the
first live turn. **No live turn has run, here or anywhere**, so everything below
is either read off the *generated* code or stated as unverified. Nothing here is
claimed to work because it validates.

### Optional tool inputs — present, already fixed, now verified at the generated call site

Seven handlers, four optional top-level inputs between them: `push_turn.lay_terms`,
`push_turn.negations`, `publish_draft_rx.ambiguities`, `log_unsupported_language.note`.
All four already defaulted to `""` with a falsy check and a comment. This pass
checked the claim against `build/livekit/agents.py` rather than against the
skill text, and the mechanism is exactly as described:

```python
async def log_unsupported_language(self, ctx, note: Annotated[str, ...], requested_language: ...):
    result = tools.log_unsupported_language.log_unsupported_language(
        note=note, requested_language=requested_language, session_id=ctx.userdata.session_id)
```

`note` carries **no default in the generated wrapper** and is passed **by
keyword**, so the model-facing schema asks for it every time and the handler
receives `""`, never `None`. A `=None` default there is unreachable code.

Every handler signature was also machine-checked against its tool YAML: the
parameter list equals `input.properties` plus the `inject` keys, exactly, for
all seven, and every optional one defaults to `""`.

One thing this pass found that is **not** the same bug and is **not ours**: the
nested properties inside `publish_draft_rx.lines[]` (`strength_unit`, `form`,
`food_relation`, …) are a JSON object the model builds, not keyword arguments,
so they can arrive as `""` for a different reason — a model filling an optional
enum with an empty string. `docs/04` §3 already rules that the **console**
coerces `""` → `None` at the tool-API boundary. The handler deliberately does
not second-guess it: nothing in this file validates a dose.

### `UNMUTE_DEV_METRICS` — present, and worse than the handover records

`metrics_enabled()` in the generated `utils/dev_metrics.py` returns false unless
the variable is set to something other than `""` or `"0"`, and when it is false
**nothing is emitted at all**. Confirmed in the generated source, not inferred.

What the handover does not say, and what this pass established:

* **`unmute dev` sets it itself** and is what writes `build/livekit/dev.log`.
  The generated `README.md` says so (*"inert unless `UNMUTE_DEV_METRICS` is
  enabled, as `unmute dev` does"*), and `compose.dev.yaml` passes the bare name
  through from the host environment with no default. So the demo path is
  covered **only if the worker is started with `unmute dev`**. The generated
  README's own alternative — `uv run python -m livekit.agents start agent.py` —
  leaves it unset and produces no log and no error.
* **The console is looking in the wrong directory anyway.**
  `console/app/config.py:43` defaults `CONSOLE_DEV_LOG` to
  `<repo>/build/livekit/dev.log`. `unmute compile vaidyavaani-agent` writes
  `<repo>/vaidyavaani-agent/build/livekit/dev.log`. One directory apart, and
  nothing errors: `console/app/main.py:305` falls back to
  `console/tests/fixtures/dev.log.sample` and serves hand-written sample
  timings, and `main.py:328` hands the same fixture to `cost.estimate`, so a ₹
  figure presented as *measured audio seconds* would be measured from a
  fixture. The metrics response does set `"fixture": true`; whether the HUD
  shows that is `web/`'s to say.

**Nothing here is this package's to write.** The fix is one variable wherever
the console is started, and it belongs to `scripts/` (`docs/04` §0):

```sh
CONSOLE_DEV_LOG="$REPO_ROOT/vaidyavaani-agent/build/livekit/dev.log"
```

`.env.example` in this package records both names and says plainly that it is a
record, not a loaded file. Also worth saying out loud: `scripts/dev-all.sh`
starts LiveKit, the tunnel, the console and Next.js — **it does not start the
agent worker at all**. There is no scripted path that produces a `dev.log`
today.

### The verbatim read-back — as strong as the architecture allows, and one real gap closed

The structural claim checks out in the generated code, more strongly than the
prompt alone would suggest. `ReadBack` is an `AgentTask` constructed with
`instructions=READ_BACK_PROMPT`, and `on_enter` runs
`await self.update_chat_ctx(llm.ChatContext())` before rendering it. So during
this step the model has **neither the conversation nor `instructions/interpreter.md`** —
including interpreter.md's standing order to use "the words of someone who has
not finished school", which is the one instruction in this package most likely
to invite a rewrite of a finished sentence. It is out of scope by construction,
not by politeness.

Two changes anyway, because the cost of each is a sentence:

1. `tasks/read-back.md` now says explicitly that the verbatim rule overrides any
   standing instruction to simplify or shorten. Belt and braces — if a later
   edit moves that guidance into the task layer, the override is already
   written down.
2. **`tasks/take-home.md` had a real gap and now does not.** It asked the model
   to pass "the confirmed read-back sentence, word for word as it was given to
   you" — i.e. from its memory of what it had just said. `take_home` runs on
   normal history, so that was a *recollection* of a clinical string, and the
   voice note the patient carries home is as clinical an artifact as the
   read-back itself. It now interpolates `{{state.readback_text}}` directly, the
   same console-rendered string the gate assigned, so the sentence in the voice
   note comes from the same place as the sentence in the read-back.

**Still honest, and still unmeasured:** in a cascade agent the final text passes
through the LLM's mouth either way. `temperature: 0`, a reset context, a
one-instruction prompt and now a direct state reference in `take_home` are the
strongest levers available, and they are not a proof. `eval/score.py` closes the
gap with evidence, and it has never run against a real `dev.log` — see
`UNMUTE_DEV_METRICS` above for why there is not one yet.

### The `think` binding — correct and complete, direct

Checked against the compiled output rather than the YAML. `build/livekit/call.py:78`:

```python
llm=openai.LLM(api_key=os.environ["OPENAI_API_KEY"], model="gpt-5.6-terra",
               reasoning_effort="none", temperature=0)
```

Model named directly, no `base_url`, no router client, credential from
`secrets:` via `os.environ`, and `compile-report.json` records the role as
`reason / openai / gpt-5.6-terra`. `slng/auto` appears nowhere in the package
except in the comments explaining why it must not be written. The router shape
kept as a comment on the binding still names every required field
(`agent_id`, `upstream.provider`, `params.world_part`) and is accurate as a
six-line swap. `reasoning_effort: "none"` stays mandatory: every agent here has
tools.

What this does **not** establish: that `gpt-5.6-terra` is a model the team's key
can call. Validation passes whatever string is written there. Only a 200 from
the provider settles it, and no such call has been made from this package.

### Known-wrong ids — none present

Grepped the whole package. `ta-IN-anand`, `hi-IN-*`, `silero`, `speed:` and
`slng/auto` appear **only inside comments that explain why they are wrong**;
not one is a live value. The compile report confirms what is actually bound:
`sarvam/bulbul:v3` with the bare voice `anand` at `language: ta|kn|hi` and no
`speed:` key, `turn-detector-mini` under `provider: livekit`, `sarvam/saaras:v3`
with no `language:`. Unverifiable without a live turn: whether `anand` is
*intelligible* across three languages — synthesis succeeded, nobody has
listened.

### The compile dance

`unmute compile` deletes and regenerates `build/livekit/`, `.venv` and all, so
`uv sync` belongs after **every** compile, and `uv` must choose its own
interpreter (3.12.15). System python 3.14 does not build that venv. This pass
ran compile then `uv sync`; `build/` is gitignored and is not part of the
commit.

## Working on this package

The CLI is not on `PATH` on this machine: `brew install slng-ai/tap/unmute`
fails with `Unexpected method 'postflight_steps' called on Cask unmute` (a
broken cask, not a broken binary) and leaves a dangling symlink at
`/opt/homebrew/bin/unmute`. The release tarball itself is fine — 0.7.4 was
extracted and run directly to validate and compile this package. `state.py` also
needs `uv` on `PATH`, which unmute uses to run it under pinned pydantic.

```bash
unmute validate            # read the output; warnings exit 0
unmute compile             # writes build/livekit/ (gitignored)
unmute dev                 # needs an LLM credential and a local livekit-server
```

`unmute compile` **wipes `build/livekit/` including its `.venv`**, so re-run
`uv sync` there after every compile, and let `uv` pick the interpreter (it
chooses 3.12.15; the system 3.14 does not work).

Handlers were smoke-tested against a stub console: all seven reach the right
path with the `X-Console-Token` header, and with the console down the gate
returns `pending`, `compare_teachback` returns `not_attempted`,
`create_voice_note` returns `failed` and `push_turn` returns `ok: false` —
every failure direction is the safe one.
