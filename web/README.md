# VaidyaVaani — web console

The clinical UI: one screen, two halves. Next.js (App Router) + TypeScript + Tailwind.

Built against [`docs/01-product-plan.md`](../docs/01-product-plan.md) §2 (screen layout and the
design-rules table) and [`docs/04-interfaces.md`](../docs/04-interfaces.md) §4–§5 (the HTTP API and
the WebSocket frames). That contract is the law — this app does not deviate from it.

## Run it

Two ways. The UI is identical in both: there is no mock branch anywhere in the
components, only a different `NEXT_PUBLIC_CONSOLE_URL` target.

### Against the dev stub (nothing else needed)

```bash
npm install
npm run mock      # terminal 1 — dev stub on 127.0.0.1:8808
npm run dev       # terminal 2 — http://127.0.0.1:3000
```

Then tap **Start consultation** and hold the two push-to-talk buttons in turn. Each
*release* advances the canned Tamil consultation, so the whole six-step flow of
docs/01 §3 is clickable: language detect → consent → two exchanges → red flag →
prescription draft → per-line confirm → read-back → teach-back → QR.

`mocks/console-mock.mjs` is a **dev-only stub**, not the console. It mints a fake
LiveKit token (so audio will not connect — the header says `no audio` and
everything visual still works), draws a placeholder QR rather than a scannable
one, and does no dose arithmetic. The real console replaces it wholesale.

### Against the real console

```bash
# console --mock, or the real thing, on 127.0.0.1:8808
NEXT_PUBLIC_CONSOLE_URL=http://127.0.0.1:8808 npm run dev
```

`NEXT_PUBLIC_CONSOLE_URL` defaults to `http://127.0.0.1:8808`, so for a local
console you can just `npm run dev`. Point it elsewhere for a tunnelled console.
Audio needs a LiveKit dev server at `ws://127.0.0.1:7880`; the console mints the
token and returns it from `POST /api/sessions`.

```bash
npm run build       # production build — must pass with no type errors
npm run typecheck   # tsc --noEmit on its own
npm test            # node's own test runner, native TS, zero extra deps
```

### Looking at the HUD's unmeasured states

The dev stub takes `METRICS_MODE` so the three states can be *looked at* rather
than assumed:

```bash
METRICS_MODE=full    npm run mock   # default: every turn fully timed
METRICS_MODE=partial npm run mock   # some turns with no latency; STT never present
METRICS_MODE=none    npm run mock   # no `metric` frame ever sent
TEACHBACK_OVERALL=not_mentioned npm run mock   # the third teach-back verdict
```

`partial` is not invented: `console/app/metrics.py:latest_frame` answers an
unusable dev.log with `{"type": "metric", "reply_latency_ms": null,
"stages": {}}`, and a `state: "unavailable"` record in unmute's log has no
`value` key at all (docs/00-HANDOVER §12).

## What is where

| Path | What it owns |
|---|---|
| `lib/types.ts` | The contract shapes from docs/04 §2 and §5, field for field |
| `lib/console-ws.ts` | The WebSocket, and the pure `reduceFrame` fold of every §5 frame into one `ConsoleView` |
| `lib/console-api.ts` | The browser half of the HTTP API, docs/04 §4 |
| `lib/livekit-room.ts` | Joins the room with the token from `POST /api/sessions`, plays agent audio |
| `lib/push-to-talk.ts` | The mic track mute — the actual push-to-talk |
| `lib/rx.ts` | Dose formatting (always digits) and the confirm-gating rules |
| `lib/i18n.ts` | Patient-half strings per script. UI chrome only — nothing clinical |
| `hooks/useSession.ts` | Wires socket + room + PTT into one object the page renders from |
| `components/` | The two panels and their parts |
| `lib/metrics-format.ts` | The one place that decides how an unmeasured number is shown |
| `mocks/console-mock.mjs` | Dev-only stub. Zero dependencies |
| `tests/` | `npm test` — the guard against a zero standing in for a measurement |

## The parts that are load-bearing

**Push-to-talk is a LiveKit track mute**, not a WebSocket message (docs/02 §1.3).
The mic track is published muted and unmuted only while a button is held;
releasing mutes it, which gives the agent a clean silence boundary and is what
lets it run `pace: snappy` turn detection. Each press also cuts agent playback
(barge-in) and sends the advisory `ptt` frame of docs/04 §5 so the console has
the ground-truth speaker side. The frame is advisory; the mute is the
enforcement.

**The confirm gate.** A line with `confidence < 0.8`, or any null in a required
field, renders highlighted and its per-line ✓ stays disabled until the doctor has
*touched every flagged field* — edited it, or looked at it and deliberately kept
it (focus-then-blur counts, so a sachet with no mg strength can be kept as "not
stated"). `CONFIRM & READ BACK` is disabled until every line is confirmed, and
the console answers `409` to `confirm-all` if we ever get that wrong, so the
promise is real on the server and not just in CSS.

**No unmeasured number is ever rendered as a number.** Every metric, latency,
score and rating band goes through [`lib/metrics-format.ts`](lib/metrics-format.ts).
A value that is missing reads *"not measured"* — never `0`, never `0 ms`, never a
green band. Three concrete traps this closes, all of which were live before:
`null <= 900` is **true** in JavaScript, so a missing latency came out rated
`good`; React renders `null` as nothing, so `{value}ms` printed a bare "ms" in
32px under the word "good"; and `line.confidence.toFixed(2)` *threw* on the
`float | None` the console really sends, taking the whole doctor's half down.

`bandFor` returns `Band | null` and the colour tables are keyed by `Band`, so a
future tile that forgets the unmeasured case **fails to compile**.
`tests/no-zero-for-unknown.test.mts` scans the components for raw interpolation
and pins the nullability of every field the console may send as null. The STT
tile in particular may read "not measured" for an entire consultation and that is
correct: Saaras streams, so unmute's only STT measurement is always unavailable
(docs/00-HANDOVER §6).

**Doses are digits**, everywhere on the doctor's half: `1-0-1`, `0.5-0-0.5`,
`500 mg`, `×5d`. "Fifteen" and "fifty" sound alike; the eye catches `15` vs `50`.

**Half doses** (docs/04 §2, changed from `int` on 2026-10-17). Schedule values are
multiples of 0.5 from 0 to 4. The schedule inputs step by 0.5 and `clampDose`
snaps anything typed onto the legal grid, so `0.25` and `1.3` cannot get in. The
card shows `0.5`, never the word "half" — same reason every other dose is digits.

On the picture card a half dose gets its **own glyph**: the same tablet with half
of it gone and a dotted ghost of the missing half, shaded so whole-vs-half
differs by mass of ink and not geometry alone. The whole tablet deliberately has
no score line down the middle, because at glyph size that is the one mark that
reads like the half's cut edge. That glyph matters more than the digits beside
it — for a patient who cannot read, it is the only representation of the dose
they can actually use.

**Strength is never spoken** in the read-back (docs/04 §2 rulings), so the
doctor's card and the picture card are the only two places a strength figure
appears. Both render it prominently rather than incidentally, and a missing
strength is highlighted on the doctor's card rather than shown as a quiet dash.

**English above the original.** The doctor's transcript puts the English
translation above the original-language line, always, so a doctor who speaks
neither can still spot an invented or dropped phrase.

**Red flags are doctor-only**, in English, with the original phrase quoted. The
patient half is never passed them.

**The patient half** shows only turns that exist in the patient's own language —
their own words, or the agent's interpretation of the doctor. A doctor turn's
`original_text` is English, so it is deliberately skipped rather than put in front
of a low-literacy patient.

## Reconnect

`state_snapshot` is always the first frame, so a dropped socket recovers by
reconnecting and re-reading it. `ConsoleSocket` backs off up to 8s and drops only
the volatile parts (interim partials) while it waits.

## Layout

Phone width stacks the halves, patient first, with no horizontal scroll at any
width; `lg` and wider puts them side by side, which is how it runs on the tablet
on the doctor's desk. The patient half is 24pt (32px) and up throughout, in the
patient's script, with icons carrying the meaning for non-readers. The picture
card prints.

Indic text uses the system Noto / Nirmala faces rather than a webfont — the OPD
network is not to be trusted.

## Known gaps

* The stub's QR is drawn, not scannable. Scanning is a real-console path.
* No audio against the stub, by design (it has no LiveKit).
* `lib/i18n.ts` strings are UI chrome and have not had native review; anything
  clinical comes from `content/`, owned by the `content-eval` session.
