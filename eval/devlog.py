"""Reader for `build/livekit/dev.log`, written against the generated emitter.

The emitter is `vaidyavaani-agent/build/livekit/utils/dev_metrics.py`, produced by
`unmute compile --target livekit`. Its record shapes are documented in
`docs/03-p0-findings.md` §14. **Everything below follows the emitter, not a
captured run** — no live turn has ever happened (docs/00 §3), so which records a
real VaidyaVaani turn emits, and in what order, is still unproven. The *shapes*
are authoritative because the emitter is the thing that writes them.

Five traps this module exists to get right, every one of them a silent failure:

1. **Lines are sentinel-prefixed.** `_emit()` prints `UNMUTE_METRIC {json}` to
   stdout, and dev.log is that stdout, so it also carries ordinary log lines.
   A reader that requires a line to *start* with `{` drops every record and
   reports "not measured" with no error.
2. **Records are nested under a key equal to their own `kind`.** A measurement's
   name is at `record["measurement"]["metric"]`, never `record["metric"]`.
   `kind` is top-level, so a `kind` check passes and the field read returns
   nothing — the exact bug docs/03 §14 found in `console/app/metrics.py`.
3. **Values are in SECONDS.** Nothing in the log is already milliseconds.
4. **Records are revised in place** — the same `id` is re-emitted with a higher
   `revision`. Dedupe or p90 is computed over duplicates.
5. **`state: "unavailable"` records have no `value` key at all**, plus a
   `reason`. Skipped, never read as zero.

There is also no `kind: "transcript"` record and no `task` field anywhere. Spoken
text is `kind: "text"` with `speaker: "assistant"`, and one utterance can arrive
as several segments sharing a `message_id`, joined with `separator_before`.
"""

from __future__ import annotations

import json
from pathlib import Path

SENTINEL = "UNMUTE_METRIC"

# docs/03 §14: `first_response` is BOTH the LLM's TTFT and the TTS's
# time-to-first-audio. Only `source` tells them apart, so every tile below is
# keyed by (metric, source-prefix) and never by name alone.
STAGE_SOURCES = {
    "llm_ttft": ("first_response", "LiveKit LLMMetrics.ttft"),
    "llm_total": ("request_duration", "LiveKit LLMMetrics.duration"),
    "tts_first_audio": ("first_response", "LiveKit TTSMetrics.ttfb"),
    "tts_total": ("request_duration", "LiveKit TTSMetrics.duration"),
    # NOT STT metrics: the only STT measurement is request_duration, emitted as
    # None for a streaming STT, and Saaras is streaming — so it is always
    # `unavailable`. The number the HUD wants is EOUMetrics.transcription_delay.
    "stt": ("transcription_delay", "LiveKit EOUMetrics"),
    "turn_detection": ("turn_detection", "LiveKit EOUMetrics"),
}


class DevLog:
    """One parsed dev.log: records deduped by (kind, id) at highest revision."""

    def __init__(self, records: list[dict]):
        self.records = records

    # -- loading ----------------------------------------------------------

    @classmethod
    def read(cls, path: Path) -> "DevLog":
        raw_records: list[dict] = []
        if not path.exists():
            return cls([])
        for line in path.read_text(encoding="utf-8").splitlines():
            rec = _parse_line(line)
            if rec is not None:
                raw_records.append(rec)
        return cls(_dedupe(raw_records))

    def __len__(self) -> int:
        return len(self.records)

    # -- selection --------------------------------------------------------

    def of_kind(self, kind: str) -> list[dict]:
        return [r for r in self.records if r.get("kind") == kind]

    def call_ids(self) -> list[str]:
        seen: list[str] = []
        for r in self.records:
            cid = r.get("call_id")
            if cid and cid not in seen:
                seen.append(cid)
        return seen

    def measurements(self, metric: str, source_prefix: str | None = None) -> list[float]:
        """Measured values for one metric, in SECONDS, unavailable ones skipped."""
        out = []
        for rec in self.of_kind("measurement"):
            m = payload(rec)
            if m.get("metric") != metric:
                continue
            if source_prefix and not str(m.get("source", "")).startswith(source_prefix):
                continue
            if m.get("state") != "measured" or "value" not in m:
                continue  # trap 5: an unavailable record has no value at all
            value = m["value"]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out.append(float(value))
        return out

    def unavailable(self) -> list[tuple[str, str]]:
        """(metric, reason) for every record the emitter could not measure."""
        return [(payload(r).get("metric", "?"), payload(r).get("reason", ""))
                for r in self.of_kind("measurement")
                if payload(r).get("state") == "unavailable"]

    def utterances(self, call_id: str, speaker: str = "assistant") -> list[dict]:
        """Whole utterances for one call, in emission order.

        Segments sharing a `message_id` are joined with `separator_before`,
        which is how the emitter splits a streamed reply. Provisional segments
        are dropped — only `final` and `incomplete` text was really spoken, and
        an `incomplete` one is reported rather than silently treated as final.
        """
        segments = [r for r in self.of_kind("text")
                    if r.get("call_id") == call_id
                    and payload(r).get("speaker") == speaker
                    and payload(r).get("state") in ("final", "incomplete")]
        segments.sort(key=_order_key)
        messages: list[dict] = []
        by_message: dict[str, dict] = {}
        for rec in segments:
            seg = payload(rec)
            key = seg.get("message_id") or rec.get("id")
            msg = by_message.get(key)
            if msg is None:
                msg = {"message_id": key, "text": "", "order": _order_key(rec),
                       "incomplete": False, "exchange_id": seg.get("exchange_id")}
                by_message[key] = msg
                messages.append(msg)
            msg["text"] += (seg.get("separator_before") or "") + (seg.get("text") or "")
            msg["incomplete"] |= seg.get("state") == "incomplete"
        return messages

    def state_changes(self, call_id: str, field: str) -> list[dict]:
        """Every `kind: "state"` change to one State field, in emission order.

        The generated `call_state.py` tells the dev reporter about each change
        as `{"origin": {...}, "changes": [{"field", "value", "by", ...}]}`. This
        is how a read-back utterance is identified without a `task` field: the
        gate's `readback_text` lands in state, and what the agent speaks after
        that is the read-back.
        """
        out = []
        for rec in sorted(self.of_kind("state"), key=_order_key):
            st = payload(rec)
            for change in st.get("changes") or []:
                if change.get("field") == field and rec.get("call_id") == call_id:
                    out.append({"order": _order_key(rec), "value": change.get("value"),
                                "by": change.get("by") or st.get("origin")})
        return out


def payload(rec: dict) -> dict:
    """The record's own fields — nested under a key equal to its `kind`."""
    body = rec.get(rec.get("kind", ""), {})
    return body if isinstance(body, dict) else {}


def _parse_line(line: str) -> dict | None:
    """One log line to a record, or None. Handles the `UNMUTE_METRIC ` prefix
    and the plain log lines that share the same stream."""
    start = line.find("{")
    if start < 0:
        return None
    if start > 0 and SENTINEL not in line[:start]:
        return None  # some other line that merely contains a brace
    try:
        rec = json.loads(line[start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(rec, dict) or "kind" not in rec:
        return None
    return rec


def _dedupe(records: list[dict]) -> list[dict]:
    """Keep the highest `revision` per (call_id, kind, id). Trap 4.

    The call id is part of the key: entity ids restart at every call, so a log
    holding more than one call has `resp_1-reply_latency` in each of them, and
    a key of (kind, id) collapses thirty runs into one. Found by running this
    over the 30-call fixture and getting two latency samples back.
    """
    best: dict[tuple, dict] = {}
    for rec in records:
        key = (rec.get("call_id"), rec.get("kind"), rec.get("id"))
        old = best.get(key)
        if old is None or rec.get("revision", 0) >= old.get("revision", 0):
            best[key] = rec
    return sorted(best.values(), key=lambda r: (r.get("call_id") or "", _order_key(r)))


def _order_key(rec: dict) -> tuple:
    return (rec.get("order", 0), rec.get("id") or "")
