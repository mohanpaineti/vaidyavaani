"""₹ per consultation. The rates themselves are placeholders; the arithmetic is not."""

from __future__ import annotations

import pytest

from app import config, cost


FIXTURE_LOG = config.FIXTURE_DEV_LOG


def test_total_is_the_sum_of_the_breakdown():
    result = cost.estimate(10, dev_log=FIXTURE_LOG)
    lines = result["breakdown"]
    usd = sum(line["usd"] or 0 for line in lines.values())
    assert result["usd_total"] == pytest.approx(usd, abs=1e-6)
    assert result["inr_total"] == pytest.approx(round(usd * cost.USD_INR, 2), abs=0.01)


def test_stt_and_tts_are_billed_on_audio_seconds_not_wall_clock():
    """docs/02 §7.1 rule 3 — a 10-minute consultation is mostly silence."""
    ten_minutes = cost.estimate(10, stt_audio_seconds=60, tts_audio_seconds=30)
    twenty_minutes = cost.estimate(20, stt_audio_seconds=60, tts_audio_seconds=30)

    # doubling wall-clock with the same audio changes neither speech line
    assert ten_minutes["breakdown"]["stt"] == twenty_minutes["breakdown"]["stt"]
    assert ten_minutes["breakdown"]["tts"] == twenty_minutes["breakdown"]["tts"]
    # and more audio does cost more
    louder = cost.estimate(10, stt_audio_seconds=120, tts_audio_seconds=30)
    assert louder["breakdown"]["stt"]["usd"] > ten_minutes["breakdown"]["stt"]["usd"]


def test_spoken_seconds_are_read_from_the_dev_log_and_listened_ones_are_not():
    """The log measures `speech_duration`; nothing in it measures transcribed audio (docs/03 §14).

    So the TTS line — the largest, and the one wall clock inflates threefold — is measured, and
    the STT line says out loud that it was assumed. Each line carries its own provenance rather
    than one flag covering both.
    """
    result = cost.estimate(10, dev_log=FIXTURE_LOG)
    assert result["inputs"]["tts_audio_seconds"] == 8.1          # 4.2 s + 3.9 s, measured
    assert result["inputs"]["tts_audio_seconds_source"] == "measured"
    assert result["inputs"]["stt_audio_seconds_source"] == "assumed_from_wall_clock"
    assert result["inputs"]["audio_seconds_source"] == "mixed"


def test_measured_speech_is_far_cheaper_than_wall_clock_would_have_billed():
    """8.1 s of speech, not 10 minutes of it — the threefold TTS overestimate in handover §6."""
    measured = cost.estimate(10, dev_log=FIXTURE_LOG)
    wall_clock = cost.estimate(10, stt_audio_seconds=600, tts_audio_seconds=600)
    assert measured["breakdown"]["tts"]["usd"] < wall_clock["breakdown"]["tts"]["usd"] / 10


def test_supplied_seconds_are_reported_as_supplied_not_as_measured():
    result = cost.estimate(10, stt_audio_seconds=60, tts_audio_seconds=30)
    assert result["inputs"]["audio_seconds_source"] == "supplied"


def test_an_unmeasured_call_says_its_audio_was_assumed(tmp_path):
    result = cost.estimate(10, dev_log=tmp_path / "nothing.log")
    assert result["inputs"]["audio_seconds_source"] == "assumed_from_wall_clock"
    assert result["inr_total"] > 0


def test_tts_is_the_largest_line_for_a_real_mix():
    """bulbul:v3 at $0.0210/min is ~3x saaras — the line that wall-clock billing would inflate."""
    result = cost.estimate(10, stt_audio_seconds=60, tts_audio_seconds=60)
    assert result["breakdown"]["tts"]["usd"] > result["breakdown"]["stt"]["usd"] * 3


def test_the_platform_bundle_is_free_on_the_local_dev_server():
    demo = cost.estimate(10, mode="demo", stt_audio_seconds=60, tts_audio_seconds=30)
    production = cost.estimate(10, mode="production", stt_audio_seconds=60, tts_audio_seconds=30)

    assert demo["breakdown"]["platform"]["usd"] == 0
    assert demo["platform_bundle_charged"] is False
    assert production["breakdown"]["platform"]["usd"] > 0
    assert production["platform_bundle_charged"] is True
    assert production["inr_total"] > demo["inr_total"]
    assert demo["mode"] == "demo" and production["mode"] == "production"


def test_an_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        cost.estimate(10, mode="whatever")


def test_the_llm_line_is_an_excluded_placeholder_not_an_estimate():
    """BYOK: the provider bill is ours and SLNG publishes no markup, so inventing it is worse."""
    result = cost.estimate(10, dev_log=FIXTURE_LOG)
    assert result["breakdown"]["llm"]["usd"] is None
    assert result["breakdown"]["llm"]["placeholder"] is True
    assert result["excludes_llm"] is True
    assert "BYOK" in result["llm_cost_excluded"]["reason"]
    assert cost.LLM_USD_PER_1K_INPUT_TOKENS is None


def test_rates_are_usd_with_one_dated_exchange_constant():
    result = cost.estimate(10, dev_log=FIXTURE_LOG)
    assert result["rates_usd_per_minute"]["tts_bulbul_v3"] == 0.0210
    assert result["rates_usd_per_minute"]["stt_saaras_v3"] == 0.0060
    assert result["usd_inr"] == cost.USD_INR
    assert result["usd_inr_as_of"] == cost.USD_INR_AS_OF
    # the soniox disagreement is carried, not silently resolved
    assert "disagree" in result["rate_notes"]["stt_soniox_rt_v5"]


def test_the_exchange_rate_is_not_baked_into_the_arithmetic():
    at_88 = cost.estimate(10, stt_audio_seconds=60, tts_audio_seconds=60, usd_inr=88.0)
    at_90 = cost.estimate(10, stt_audio_seconds=60, tts_audio_seconds=60, usd_inr=90.0)
    assert at_88["usd_total"] == at_90["usd_total"]
    assert at_90["inr_total"] > at_88["inr_total"]


def test_zero_length_call_costs_nothing():
    assert cost.estimate(0, stt_audio_seconds=0, tts_audio_seconds=0)["inr_total"] == 0


def test_cost_endpoint(client):
    body = client.get("/api/cost?minutes=10").json()
    assert body["inr_total"] >= 0
    assert body["mode"] == "demo"
    assert "breakdown" in body

    production = client.get("/api/cost?minutes=10&mode=production").json()
    assert production["platform_bundle_charged"] is True
    assert client.get("/api/cost?minutes=10&mode=guess").status_code == 422
