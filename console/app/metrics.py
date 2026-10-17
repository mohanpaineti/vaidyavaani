"""Metrics for the HUD, read from unmute's own dev log.

The generated LiveKit worker writes one `UNMUTE_METRIC {json}` line per record to
`build/livekit/dev.log`. **The shapes below are read off the generated emitter**
(`build/livekit/utils/dev_metrics.py`, documented in `docs/03-p0-findings.md` §14) — not guessed,
and no longer matched against a table of alternative spellings. Point the reader anywhere with
`CONSOLE_DEV_LOG`; `tests/fixtures/dev.log.sample` is the §14 sample.

The envelope, and the five traps that come with it:

```json
{"version":2,"kind":"measurement","call_id":"…","id":"…","revision":1,"order":7,
 "measurement":{"metric":"first_response","unit":"seconds","source":"LiveKit LLMMetrics.ttft",
                "state":"measured","value":0.26}}
```

1. **Records are nested under a key equal to their own `kind`.** A measurement's name is at
   `record["measurement"]["metric"]`, never at the top level. `kind` *is* top-level, so a naive
   kind-check passes and the field read then silently returns nothing — that was the bug this file
   shipped with, and it left every HUD tile `None` with no error.
2. **Values are in SECONDS.** Nothing in the log is already milliseconds; the HUD wants ms, so
   every value is multiplied by 1000 exactly once, here.
3. **`state` is `measured` or `unavailable`, and an unavailable record has no `value` key at all.**
   Skipped, never read as zero.
4. **Records are revised in place**: the same `id` is re-emitted with a higher `revision` whenever
   a field changes. Deduped by `(call_id, id)` keeping the highest revision, or p90 double-counts.
5. **Names collide across stages; `source` is the only disambiguator.** `first_response` is both
   the LLM's TTFT *and* the TTS's time-to-first-audio, so name matching alone cannot work.

And one that is not the parser's fault: **nothing is emitted at all unless `UNMUTE_DEV_METRICS` is
set** to something other than `""`/`"0"` in the worker's environment. An empty HUD is that, before
it is anything else.

LiveKit's own rating bands, quoted rather than invented: green ≤ 900 ms, slow > 900 ms,
over limit > 1200 ms.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from . import config

log = logging.getLogger("console.metrics")

RATING_GREEN_MS = 900
RATING_OVER_LIMIT_MS = 1200

MAX_LINES = 5000  # we only ever need the tail

SENTINEL = "UNMUTE_METRIC"


def _source_has(fragment: str) -> Callable[[str], bool]:
    def predicate(source: str) -> bool:
        return fragment.lower() in source.lower()

    return predicate


def _any_source(_source: str) -> bool:
    return True


# HUD tile -> (measurement.metric, predicate over measurement.source).
#
# The source predicate is not decoration: `first_response` and `request_duration` are each emitted
# by two different stages, and only `source` tells them apart (§14).
TILES: dict[str, tuple[str, Callable[[str], bool]]] = {
    "reply_latency_ms": ("reply_latency", _any_source),
    # The `stt` tile deliberately does NOT come from an STT metric. The only STT measurement is
    # `request_duration` from `LiveKit STTMetrics.duration`, emitted as `None if metric.streamed`
    # — and Saaras is streaming, so that record is always `state: "unavailable"`. The number the
    # tile wants is the EOU transcription delay.
    "stt": ("transcription_delay", _source_has("EOUMetrics")),
    "llm_ttft": ("first_response", _source_has("LLMMetrics")),
    "llm_total": ("request_duration", _source_has("LLMMetrics")),
    "tts_first_audio": ("first_response", _source_has("TTSMetrics")),
    "tts_total": ("request_duration", _source_has("TTSMetrics")),
    "turn_detection": ("turn_detection", _source_has("EOUMetrics")),
    "tool_duration": ("tool_duration", _any_source),
    "first_speech": ("first_speech", _any_source),
}

# Stage tiles the HUD renders, in the order docs/04 §5 lists them.
STAGE_TILES = (
    "stt",
    "llm_ttft",
    "tts_first_audio",
    "llm_total",
    "tts_total",
    "turn_detection",
    "tool_duration",
    "first_speech",
)

# Audio seconds, for cost.py. STT and TTS are billed per minute of *audio*, not of wall clock
# (docs/03 §11), so these are the numbers that price a consultation.
#
# `speech_duration` is the only duration-of-audio measurement §14 records, and §14 does not record
# a source string for it, so it is matched by name alone. If a real log ever shows two emitters of
# that name, this needs a source check like the tiles above.
#
# There is deliberately no listening figure: the emitter has no measurement of transcribed audio
# seconds at all (the one STT measurement is a request duration, and it is always unavailable).
# `listen_seconds` is therefore always None, and cost.py says "assumed" for that line rather than
# presenting a wall-clock guess as measured.
SPEAK_SECONDS_METRIC = "speech_duration"


def audio_seconds(path: Path | None = None, session_id: str | None = None) -> dict:
    """Measured speaking and listening seconds, summed over the log. None when nothing is logged.

    `None` is the honest answer when unmute has told us nothing — `cost.py` then says that line was
    assumed rather than quietly presenting it as measured. `listen_seconds` is *always* None: see
    the note above, nothing in the log measures transcribed audio.
    """
    totals: dict[str, float | None] = {"speak_seconds": None, "listen_seconds": None}
    for measurement in _measurements(path, session_id):
        if measurement["metric"] == SPEAK_SECONDS_METRIC:
            seconds = measurement["value_seconds"]
            totals["speak_seconds"] = (totals["speak_seconds"] or 0.0) + seconds
    if totals["speak_seconds"] is not None:
        totals["speak_seconds"] = round(totals["speak_seconds"], 3)
    return totals


def rating(ms: float | None) -> str:
    if ms is None:
        return "unknown"
    if ms <= RATING_GREEN_MS:
        return "green"
    if ms <= RATING_OVER_LIMIT_MS:
        return "slow"
    return "over_limit"


def p90(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 1)
    # nearest-rank p90, which is what a tile wants
    index = min(len(ordered) - 1, max(0, round(0.9 * (len(ordered) - 1))))
    return round(ordered[index], 1)


def _tile_for(metric: str, source: str) -> str | None:
    for tile, (name, source_matches) in TILES.items():
        if metric == name and source_matches(source):
            return tile
    return None


def read_measurements(path: Path | None = None, session_id: str | None = None) -> list[dict]:
    """Every `"kind":"measurement"` record in the log, deduped by id, in emission order.

    Whole records, exactly as logged — the nested `measurement` payload is still nested. Never
    raises. Use `_measurements()` for the flattened, usable view.
    """
    target = _target(path)
    if not target.exists():
        return []
    try:
        with target.open("r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()[-MAX_LINES:]
    except OSError:
        log.exception("could not read the dev log at %s", target)
        return []

    # Keyed by (call_id, id): the same entity is re-emitted with a higher `revision` whenever a
    # field changes, and counting both copies would double-count it in p90 and the median.
    latest: dict[tuple[Any, Any], tuple[int, int, dict]] = {}
    for sequence, raw in enumerate(lines):
        raw = raw.strip()
        if not raw:
            continue
        # Lines are prefixed `UNMUTE_METRIC `; everything from the first brace is the record.
        start = raw.find("{")
        if start < 0:
            continue
        try:
            record = json.loads(raw[start:])
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("kind") != "measurement":
            continue
        if not isinstance(record.get("measurement"), dict):
            continue
        if session_id and not _belongs_to(record, session_id):
            continue
        key = (record.get("call_id"), record.get("id", sequence))
        revision = record.get("revision")
        revision = revision if isinstance(revision, int) else 0
        order = record.get("order")
        order = order if isinstance(order, int) else sequence
        previous = latest.get(key)
        if previous is None or revision >= previous[0]:
            latest[key] = (revision, order, record)

    return [record for _revision, _order, record in sorted(latest.values(), key=lambda e: e[1])]


def _belongs_to(record: dict, session_id: str) -> bool:
    """unmute labels records with its own `call_id`, which is not our session id.

    Nothing in the log carries a console session id, so a record is excluded only when it names a
    session explicitly and names a different one — otherwise filtering would empty the HUD.
    """
    named = record.get("session_id")
    return named is None or named == session_id


def _measurements(path: Path | None = None, session_id: str | None = None) -> list[dict]:
    """Usable measurements: nesting resolved, unavailable ones dropped, seconds converted to ms.

    Each entry is `{metric, source, state, value_seconds, value_ms, tile, record}`.
    """
    usable: list[dict] = []
    for record in read_measurements(path, session_id):
        payload = record["measurement"]
        metric = payload.get("metric")
        if not isinstance(metric, str):
            continue
        # `state: "unavailable"` records carry a `reason` and NO `value` key. Reading one as zero
        # would drag every average down — the STT request_duration record is always one of these.
        if payload.get("state") != "measured":
            continue
        value = payload.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        source = payload.get("source") or ""
        seconds = float(value)
        usable.append(
            {
                "metric": metric,
                "source": source,
                "state": payload.get("state"),
                "value_seconds": seconds,
                "value_ms": seconds * 1000,  # the log is seconds; the HUD is ms. Converted once.
                "tile": _tile_for(metric, source if isinstance(source, str) else ""),
                "record": record,
            }
        )
    return usable


def _series(path: Path | None, session_id: str | None) -> dict[str, list[float]]:
    series: dict[str, list[float]] = {tile: [] for tile in TILES}
    for measurement in _measurements(path, session_id):
        tile = measurement["tile"]
        if tile is not None:
            series[tile].append(measurement["value_ms"])
    return series


def summarise(path: Path | None = None, session_id: str | None = None) -> dict:
    """Stage timings + p90 for the HUD and `GET /api/sessions/{id}/metrics`."""
    series = _series(path, session_id)
    replies = series["reply_latency_ms"]
    target = _target(path)
    stages = {
        name: {
            "p90_ms": p90(series[name]),
            "last_ms": round(series[name][-1], 1) if series[name] else None,
            "samples": len(series[name]),
        }
        for name in STAGE_TILES
    }
    return {
        "source": str(target),
        "source_present": target.exists(),
        "samples": len(replies),
        "reply_latency_ms": {
            "last": round(replies[-1], 1) if replies else None,
            "median": p90(replies) if len(replies) < 2 else _median(replies),
            "p90": p90(replies),
            "worst": round(max(replies), 1) if replies else None,
            "rating": rating(p90(replies)),
        },
        "stages": stages,
        "bands_ms": {"green": RATING_GREEN_MS, "over_limit": RATING_OVER_LIMIT_MS},
    }


def _target(path: Path | None) -> Path:
    return Path(path) if path is not None else config.DEV_LOG_PATH


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 1)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 1)


def latest_frame(path: Path | None = None, session_id: str | None = None) -> dict | None:
    """The newest measurements as the `metric` WS frame from docs/04 §5, or None.

    One record is one stage, not one turn — the stages of a reply arrive as separate records — so
    the frame carries the latest value seen for each of the three HUD stages, not just whatever
    the last line happened to be.
    """
    series = _series(path, session_id)
    if not any(series.values()):
        return None
    reply = round(series["reply_latency_ms"][-1], 1) if series["reply_latency_ms"] else None
    stages = {
        name: round(series[name][-1], 1)
        for name in ("stt", "llm_ttft", "tts_first_audio")
        if series[name]
    }
    return {"type": "metric", "reply_latency_ms": reply, "stages": stages}
