# Stand-in for unmute's `build/livekit/dev.log`.

**Shapes are confirmed; timings are not.** Lines 1–12 are `docs/03-p0-findings.md` §14's sample
verbatim — synthesized there from the *generated emitter* `build/livekit/utils/dev_metrics.py`,
which is the thing that writes the log, so the field names, nesting, units and `state` values are
authoritative. Everything after it is a second exchange written here in exactly those shapes, so the
parser is exercised over more than one turn (p90 over one sample proves nothing).

**No number in this file was measured.** No live turn has ever run (handover §12). These are
plausible timings for a parser fixture, never evidence of latency — do not quote them anywhere.

What the sample deliberately contains, each of which broke the old parser or would have:

* records **nested under a key equal to their own `kind`** — a measurement's name is at
  `measurement.metric`, not at the top level;
* **seconds**, never milliseconds;
* two `state: "unavailable"` records (the streaming-STT `request_duration`) with **no `value` key**;
* the same `id` at `revision` 1 and 2 (`resp_1-reply_latency`), which double-counts without dedupe;
* `first_response` from **both** `LLMMetrics.ttft` and `TTSMetrics.ttfb`, told apart only by
  `source`;
* non-measurement records (`call`, `exchange`, `operation`, `log`) interleaved.

One caveat on `speech_duration`: §14 lists the metric but records no `source` string for it, so the
`LiveKit AgentSession` source here is a placeholder. `app/metrics.py` matches that metric by name
alone for exactly that reason; if a real log shows two emitters of the name, add a source check.
