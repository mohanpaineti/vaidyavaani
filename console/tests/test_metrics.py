"""Metrics read out of unmute's dev log.

The shapes under test are the generated emitter's, documented in `docs/03-p0-findings.md` §14.
Every trap §14 lists has a test here, because the parser this replaced passed its own suite while
producing `samples: 0` and every tile `None` on a realistic log: the old tests only asserted that
nothing raised. These assert actual tile values.
"""

from __future__ import annotations

import json
from pathlib import Path

from app import config, metrics


def _record(order: int, payload: dict, *, record_id: str, revision: int = 1) -> str:
    return "UNMUTE_METRIC " + json.dumps(
        {
            "version": 2,
            "kind": "measurement",
            "call_id": "call_test",
            "id": record_id,
            "revision": revision,
            "order": order,
            "measurement": payload,
        }
    )


def _log(tmp_path: Path, lines: list[str]) -> Path:
    target = tmp_path / "dev.log"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


# ── the bug that shipped ────────────────────────────────────────────────────────────────────────


def test_a_realistic_log_actually_populates_the_tiles():
    """The regression test for the original bug: 9 records in, 0 samples out, every tile None.

    Asserting "no exception" would have passed on the broken parser. These are tile values.
    """
    summary = metrics.summarise(config.FIXTURE_DEV_LOG)

    assert summary["samples"] == 2                       # two exchanges, deduped
    assert summary["reply_latency_ms"]["last"] == 1180.0  # 1.18 s → ms
    assert summary["reply_latency_ms"]["worst"] == 1180.0
    assert summary["reply_latency_ms"]["rating"] == "slow"   # p90 1180 ms: >900, not yet >1200

    stages = summary["stages"]
    assert stages["stt"]["samples"] == 2
    assert stages["stt"]["last_ms"] == 402.0             # transcription_delay 0.402 s
    assert stages["llm_ttft"]["last_ms"] == 396.0        # first_response @ LLMMetrics.ttft
    assert stages["tts_first_audio"]["last_ms"] == 255.0  # first_response @ TTSMetrics.ttfb
    assert stages["llm_total"]["last_ms"] == 910.0       # request_duration @ LLMMetrics.duration
    assert stages["tool_duration"]["last_ms"] == 64.0    # 0.064 s, not 64 s
    # request_duration is emitted by both the LLM and TTS; source keeps the two tiles apart
    assert stages["tts_total"]["last_ms"] == 620.0       # request_duration @ TTSMetrics.duration
    assert all(stage["p90_ms"] is not None for stage in stages.values() if stage["samples"])


def test_the_name_is_read_from_the_nested_payload_not_the_top_level(tmp_path):
    """§14's bug: `kind` is top-level, the metric name is one level down under that same key."""
    log = _log(
        tmp_path,
        [
            _record(
                1,
                {
                    "metric": "reply_latency",
                    "unit": "seconds",
                    "source": "LiveKit LLM node",
                    "state": "measured",
                    "value": 0.84,
                },
                record_id="resp_1-reply_latency",
            )
        ],
    )
    summary = metrics.summarise(log)
    assert summary["samples"] == 1
    assert summary["reply_latency_ms"]["last"] == 840.0

    # and a record that put the same name at the top level is NOT read — the real log never does
    flat = tmp_path / "flat.log"
    flat.write_text(
        'UNMUTE_METRIC {"version":2,"kind":"measurement","id":"x","metric":"reply_latency",'
        '"state":"measured","value":0.84}\n',
        encoding="utf-8",
    )
    assert metrics.summarise(flat)["samples"] == 0


# ── the five traps ──────────────────────────────────────────────────────────────────────────────


def test_values_are_seconds_and_are_converted_once(tmp_path):
    """Nothing in the log is already milliseconds."""
    log = _log(
        tmp_path,
        [
            _record(
                1,
                {
                    "metric": "transcription_delay",
                    "unit": "seconds",
                    "source": "LiveKit EOUMetrics",
                    "state": "measured",
                    "value": 0.31,
                },
                record_id="resp_1-transcription_delay",
            )
        ],
    )
    assert metrics.summarise(log)["stages"]["stt"]["last_ms"] == 310.0


def test_an_unavailable_record_has_no_value_and_is_skipped_not_read_as_zero(tmp_path):
    """Streaming STT always emits this one. Counting it as 0 would drag every average down."""
    log = _log(
        tmp_path,
        [
            _record(
                1,
                {
                    "metric": "request_duration",
                    "unit": "seconds",
                    "source": "LiveKit LLMMetrics.duration",
                    "state": "measured",
                    "value": 0.74,
                },
                record_id="llm-1-request_duration",
            ),
            _record(
                2,
                {
                    "metric": "request_duration",
                    "unit": "seconds",
                    "source": "LiveKit STTMetrics.duration",
                    "state": "unavailable",
                    "reason": "Streaming STT does not measure request duration.",
                },
                record_id="stt-duration-1",
            ),
        ],
    )
    stages = metrics.summarise(log)["stages"]
    assert stages["llm_total"] == {"p90_ms": 740.0, "last_ms": 740.0, "samples": 1}
    # the unavailable record contributed nothing at all, to any tile
    assert stages["tts_total"]["samples"] == 0
    assert stages["stt"]["samples"] == 0


def test_a_revised_record_is_counted_once_at_its_highest_revision(tmp_path):
    """Same `id`, higher `revision`. Counting both doubles the sample count and skews p90."""
    payload = {
        "metric": "reply_latency",
        "unit": "seconds",
        "source": "LiveKit LLM node",
        "state": "measured",
        "value": 0.84,
    }
    revised = dict(payload, source="LiveKit playback", value=0.86)
    log = _log(
        tmp_path,
        [
            _record(1, payload, record_id="resp_1-reply_latency", revision=1),
            _record(1, revised, record_id="resp_1-reply_latency", revision=2),
        ],
    )
    summary = metrics.summarise(log)
    assert summary["samples"] == 1
    assert summary["reply_latency_ms"]["last"] == 860.0  # the higher revision wins


def test_first_response_is_split_by_source_not_by_name(tmp_path):
    """`first_response` is both LLM TTFT and TTS time-to-first-audio; only `source` tells them apart."""
    log = _log(
        tmp_path,
        [
            _record(
                1,
                {
                    "metric": "first_response",
                    "unit": "seconds",
                    "source": "LiveKit LLMMetrics.ttft",
                    "state": "measured",
                    "value": 0.26,
                },
                record_id="llm-1-first_response",
            ),
            _record(
                2,
                {
                    "metric": "first_response",
                    "unit": "seconds",
                    "source": "LiveKit TTSMetrics.ttfb",
                    "state": "measured",
                    "value": 0.21,
                },
                record_id="tts-1-first_response",
            ),
        ],
    )
    stages = metrics.summarise(log)["stages"]
    assert stages["llm_ttft"] == {"p90_ms": 260.0, "last_ms": 260.0, "samples": 1}
    assert stages["tts_first_audio"] == {"p90_ms": 210.0, "last_ms": 210.0, "samples": 1}


def test_the_stt_tile_comes_from_eou_transcription_delay(tmp_path):
    """It cannot come from STT metrics at all: the only one is always unavailable (§14)."""
    log = _log(
        tmp_path,
        [
            _record(
                1,
                {
                    "metric": "transcription_delay",
                    "unit": "seconds",
                    "source": "LiveKit EOUMetrics",
                    "state": "measured",
                    "value": 0.31,
                },
                record_id="resp_1-transcription_delay",
            ),
            _record(
                2,
                {
                    "metric": "request_duration",
                    "unit": "seconds",
                    "source": "LiveKit STTMetrics.duration",
                    "state": "unavailable",
                    "reason": "Streaming STT does not measure request duration.",
                },
                record_id="stt-duration-1",
            ),
        ],
    )
    assert metrics.summarise(log)["stages"]["stt"]["last_ms"] == 310.0


# ── the rest of the surface ─────────────────────────────────────────────────────────────────────


def test_measurements_are_read_from_the_fixture_log():
    records = metrics.read_measurements(config.FIXTURE_DEV_LOG)
    assert all(record["kind"] == "measurement" for record in records)
    assert all(isinstance(record["measurement"], dict) for record in records)
    # 20 measurement lines, two of which are the same id at two revisions
    assert len(records) == 19


def test_non_measurement_records_are_ignored():
    kinds = {record["kind"] for record in metrics.read_measurements(config.FIXTURE_DEV_LOG)}
    assert kinds == {"measurement"}


def test_ratings_quote_livekits_bands():
    assert metrics.rating(800) == "green"
    assert metrics.rating(1000) == "slow"
    assert metrics.rating(1500) == "over_limit"
    assert metrics.rating(None) == "unknown"


def test_a_missing_log_is_not_an_error(tmp_path: Path):
    summary = metrics.summarise(tmp_path / "nope.log")
    assert summary["samples"] == 0
    assert summary["source_present"] is False
    assert summary["reply_latency_ms"]["p90"] is None


def test_a_log_of_only_unavailable_records_reports_nothing_rather_than_zero(tmp_path):
    log = _log(
        tmp_path,
        [
            _record(
                1,
                {
                    "metric": "request_duration",
                    "unit": "seconds",
                    "source": "LiveKit STTMetrics.duration",
                    "state": "unavailable",
                    "reason": "Streaming STT does not measure request duration.",
                },
                record_id="stt-duration-1",
            )
        ],
    )
    summary = metrics.summarise(log)
    assert summary["samples"] == 0
    assert summary["reply_latency_ms"]["p90"] is None
    assert metrics.latest_frame(log) is None


def test_garbage_lines_do_not_stop_the_parse(tmp_path):
    good = _record(
        2,
        {
            "metric": "reply_latency",
            "unit": "seconds",
            "source": "LiveKit LLM node",
            "state": "measured",
            "value": 0.84,
        },
        record_id="resp_1-reply_latency",
    )
    log = _log(tmp_path, ["UNMUTE_METRIC {not json", "", "plain stdout from the worker", good])
    assert metrics.summarise(log)["samples"] == 1


def test_latest_frame_matches_the_websocket_shape():
    frame = metrics.latest_frame(config.FIXTURE_DEV_LOG)
    assert frame is not None
    assert frame["type"] == "metric"
    assert frame["reply_latency_ms"] == 1180.0
    # docs/04 §5: the frame carries the three stage tiles, each with a real number
    assert frame["stages"] == {"stt": 402.0, "llm_ttft": 396.0, "tts_first_audio": 255.0}


# ── audio seconds, for cost.py ──────────────────────────────────────────────────────────────────


def test_speaking_seconds_are_summed_from_speech_duration():
    """TTS is billed per minute of audio, so this is the number cost.py prices (docs/03 §11)."""
    audio = metrics.audio_seconds(config.FIXTURE_DEV_LOG)
    assert audio["speak_seconds"] == 8.1  # 4.2 + 3.9, already seconds — not multiplied by 1000


def test_listening_seconds_are_never_measured():
    """Nothing in the log measures transcribed audio; None keeps cost.py honest about it."""
    assert metrics.audio_seconds(config.FIXTURE_DEV_LOG)["listen_seconds"] is None


def test_audio_seconds_are_none_when_nothing_was_logged(tmp_path):
    """None, not zero — a cost built on it must be able to say it was assumed."""
    audio = metrics.audio_seconds(tmp_path / "nothing.log")
    assert audio == {"speak_seconds": None, "listen_seconds": None}


def test_metrics_endpoint_falls_back_to_the_sample(client, store):
    session = store.create(patient_language="ta")
    body = client.get(f"/api/sessions/{session.state.session_id}/metrics").json()
    assert "reply_latency_ms" in body
    assert body["bands_ms"]["green"] == 900
    assert body["samples"] == 2
