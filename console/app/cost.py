"""Rupees per consultation.

`unmute dev` measures latency for us; it does not price the call. This does.

Three rules from docs/02 §7.1, each of which is a way to get the number wrong:

1. **Demo cost ≠ production cost.** The platform bundle is $0 on a local LiveKit server, so the
   response says which number it is (`mode`).
2. **LLM cost is not SLNG's to publish.** The Context Router is BYOK — the provider bill is ours
   and there is no documented markup — so that line is a flagged placeholder, never an estimate.
3. **Bill audio seconds, not wall-clock minutes.** STT and TTS are charged per minute of *audio*.
   A 10-minute consultation is mostly silence, so wall-clock badly overestimates TTS, the biggest
   line. `metrics.audio_seconds()` reads the measured speaking seconds out of `dev.log`, so that
   line is derived rather than assumed. Listening seconds are *not* in the log at all — the only
   STT measurement is a request duration and streaming STT never reports one (docs/03 §14) — so
   the STT line falls back to a stated fraction of wall clock and says `assumed_from_wall_clock`
   next to itself. Each line carries its own provenance; a slide may quote only the measured one
   as measured.

Rates are USD, with one dated `USD_INR` constant, rather than an exchange rate baked into the
arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import metrics

# ─────────────────────────────────────────────────────────────────────────────────────────────
# RATES — USD per minute, from P0 (docs/02 §7.1): the live SLNG catalog and docs.slng.ai, two
# agreeing sources. The catalog's `microdollars_per_min` ÷ 10,000 = USD/min.
USD_PER_MINUTE = {
    "stt_saaras_v3": 0.0060,          # sarvam/saaras:v3 — listen, both sides
    "tts_bulbul_v3": 0.0210,          # sarvam/bulbul:v3 — the largest line, by ~3×
    "stt_nova_3": 0.0030,             # deepgram/nova:3 — listen fallback 1
    "stt_soniox_rt_v5": 0.0038,       # ⚠ catalog says 0.0038, docs say 0.0028; sources disagree
    "platform_bundle": 0.0030,        # per agent-minute — $0 on the local dev server
}
RATE_NOTES = {
    "stt_soniox_rt_v5": "catalog $0.0038 vs docs $0.0028 — sources disagree; catalog figure used",
    "platform_bundle": "$0 on a local LiveKit server; charged only on the hosted target",
}

# One dated constant, shown on the slide, rather than an exchange rate baked into the code.
USD_INR = 88.0
USD_INR_AS_OF = "2026-10-17"

# The LLM line. The router is BYOK: the provider bill is the team's and SLNG publishes no markup,
# so this is a placeholder and is reported as one. It is never silently added to the total.
LLM_USD_PER_1K_INPUT_TOKENS: float | None = None
LLM_USD_PER_1K_OUTPUT_TOKENS: float | None = None
LLM_RATES_ARE_PLACEHOLDERS = True
# ─────────────────────────────────────────────────────────────────────────────────────────────

# Used only when nothing has been measured, and always reported as `assumed_from_wall_clock`.
# A two-way interpreted consultation: both sides' speech is transcribed, the agent speaks less
# than it hears. These are stated assumptions, not findings.
ASSUMED_LISTEN_FRACTION = 0.55
ASSUMED_SPEAK_FRACTION = 0.30

MODES = ("demo", "production")


@dataclass
class CostBreakdown:
    """USD per line item. `llm` is None while the BYOK rate is unknown."""

    stt: float
    tts: float
    platform: float
    llm: float | None = None

    @property
    def total_usd(self) -> float:
        return round(self.stt + self.tts + self.platform + (self.llm or 0.0), 6)

    def as_dict(self, usd_inr: float) -> dict[str, Any]:
        def inr(value: float | None) -> float | None:
            return None if value is None else round(value * usd_inr, 2)

        return {
            "stt": {"usd": round(self.stt, 6), "inr": inr(self.stt)},
            "tts": {"usd": round(self.tts, 6), "inr": inr(self.tts)},
            "platform": {"usd": round(self.platform, 6), "inr": inr(self.platform)},
            "llm": {"usd": self.llm, "inr": inr(self.llm), "placeholder": True},
        }


def estimate(
    minutes: float,
    *,
    mode: str = "demo",
    stt_audio_seconds: float | None = None,
    tts_audio_seconds: float | None = None,
    dev_log: Path | None = None,
    session_id: str | None = None,
    usd_inr: float = USD_INR,
) -> dict[str, Any]:
    """₹ for one consultation.

    `minutes` is wall-clock call duration and prices only the platform bundle, which really is
    charged per agent-minute. STT and TTS are priced from audio seconds: measured ones when
    `dev.log` has them, the explicitly passed ones, or — as a last resort, clearly flagged — a
    documented fraction of wall-clock.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    minutes = max(0.0, float(minutes))

    measured = metrics.audio_seconds(dev_log, session_id)
    # Each line records its own provenance. The log measures spoken seconds (`speech_duration`)
    # but nothing measures transcribed seconds at all — the one STT measurement is a request
    # duration and it is always `state: "unavailable"` on streaming STT (docs/03 §14) — so in
    # practice TTS is measured and STT is assumed, and the response has to be able to say so.
    stt_source = "supplied" if stt_audio_seconds is not None else "measured"
    tts_source = "supplied" if tts_audio_seconds is not None else "measured"
    if stt_audio_seconds is None:
        stt_audio_seconds = measured["listen_seconds"]
    if tts_audio_seconds is None:
        tts_audio_seconds = measured["speak_seconds"]

    # Nothing measured and nothing supplied. Say so loudly rather than quietly assuming.
    if stt_audio_seconds is None:
        stt_audio_seconds = minutes * 60 * ASSUMED_LISTEN_FRACTION
        stt_source = "assumed_from_wall_clock"
    if tts_audio_seconds is None:
        tts_audio_seconds = minutes * 60 * ASSUMED_SPEAK_FRACTION
        tts_source = "assumed_from_wall_clock"

    if stt_source == tts_source:
        source = stt_source
    else:
        source = "mixed"

    breakdown = CostBreakdown(
        stt=stt_audio_seconds / 60 * USD_PER_MINUTE["stt_saaras_v3"],
        tts=tts_audio_seconds / 60 * USD_PER_MINUTE["tts_bulbul_v3"],
        platform=(minutes * USD_PER_MINUTE["platform_bundle"] if mode == "production" else 0.0),
        llm=None,
    )

    return {
        "inr_total": round(breakdown.total_usd * usd_inr, 2),
        "usd_total": breakdown.total_usd,
        "breakdown": breakdown.as_dict(usd_inr),
        "mode": mode,
        "platform_bundle_charged": mode == "production",
        "inputs": {
            "minutes": minutes,
            "stt_audio_seconds": round(stt_audio_seconds, 1),
            "tts_audio_seconds": round(tts_audio_seconds, 1),
            "audio_seconds_source": source,
            "stt_audio_seconds_source": stt_source,
            "tts_audio_seconds_source": tts_source,
        },
        "rates_usd_per_minute": dict(USD_PER_MINUTE),
        "rate_notes": dict(RATE_NOTES),
        "usd_inr": usd_inr,
        "usd_inr_as_of": USD_INR_AS_OF,
        "llm_cost_excluded": {
            "reason": (
                "The SLNG Context Router is BYOK: the provider bill is ours and SLNG publishes no "
                "markup, so an LLM figure here would be invented. Excluded from the total and "
                "reported as a placeholder."
            ),
            "placeholder": LLM_RATES_ARE_PLACEHOLDERS,
        },
        "excludes_llm": True,
    }

