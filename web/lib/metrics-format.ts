/**
 * One place that decides how an unmeasured number is shown.
 *
 * The whole credibility of this project rests on the difference between
 * *measured* and *assumed* (docs/00-HANDOVER §13). On a HUD that means a value
 * we do not have must never leave the screen looking like a value we do have.
 * Three specific ways that happens, all of which were live in this file's
 * absence:
 *
 *   1. A missing latency falls through as `0` and reads "0 ms" — the best
 *      possible number, from no measurement at all.
 *   2. A missing latency is `null`, and `null <= 900` is **true** in JavaScript,
 *      so the rating band comes out green. A judge sees a green "good" tile for
 *      a turn nobody timed.
 *   3. React renders `null` as nothing, so `{value}ms` prints a bare "ms" in
 *      32px type under the label "last reply · good".
 *
 * So: `bandFor` returns `null` for anything that is not a finite number, and the
 * band lookup tables are keyed by `Band` only — passing the null through to a
 * colour class is a *type error*, which is the guard that survives refactoring.
 * `formatMs` and `formatCount` never produce a digit they were not given.
 *
 * Why values genuinely arrive missing, so this is not defensive theatre:
 *   · `console/app/metrics.py:latest_frame` emits `reply_latency_ms: None` and an
 *     empty `stages` dict when the dev log has no usable record.
 *   · `state: "unavailable"` records in unmute's dev.log have **no `value` key at
 *     all** (docs/00-HANDOVER §12) and must be skipped, not read as zero.
 *   · The STT stage may never be populated from STT metrics at all — see
 *     `STT_STAGE_NOTE` below.
 */

/** Anything a metric may actually be by the time it reaches a component. */
export type MetricValue = number | null | undefined;

/** The single wording for "we do not have this number". Never "0", never "—". */
export const UNMEASURED = "not measured";

/** Shorter form, for places too tight for the sentence. Still not a digit. */
export const UNMEASURED_SHORT = "n/m";

/** LiveKit's own bands, quoted rather than invented (docs/00-HANDOVER §11). */
export const BAND_GOOD_MS = 900;
export const BAND_LIMIT_MS = 1200;

export type Band = "good" | "slow" | "over";

/** True only for a real, finite measurement. `null`, `undefined` and NaN are not. */
export function isMeasured(value: MetricValue): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/**
 * The rating band, or `null` when there is nothing to rate.
 *
 * Returning `null` rather than a default band is the whole point: `BAND_CLASS`
 * and `BAND_LABEL` below are keyed by `Band`, so a caller that forgets the
 * unmeasured case cannot compile.
 */
export function bandFor(ms: MetricValue): Band | null {
  if (!isMeasured(ms)) return null;
  if (ms <= BAND_GOOD_MS) return "good";
  if (ms <= BAND_LIMIT_MS) return "slow";
  return "over";
}

export const BAND_CLASS: Record<Band, string> = {
  good: "text-emerald-300",
  slow: "text-amber-300",
  over: "text-red-300",
};

export const BAND_BAR_CLASS: Record<Band, string> = {
  good: "bg-emerald-400",
  slow: "bg-amber-400",
  over: "bg-red-400",
};

export const BAND_LABEL: Record<Band, string> = {
  good: "good",
  slow: "slow",
  over: "over limit",
};

/** Slate, not green. An unmeasured value gets the colour of an absence. */
export const UNMEASURED_CLASS = "text-slate-500";

/** `840 ms`, or the words. Never `0 ms` for a value we do not have. */
export function formatMs(value: MetricValue, fallback: string = UNMEASURED): string {
  return isMeasured(value) ? `${round1(value)} ms` : fallback;
}

/** The bare number, for places that print their own unit. */
export function formatNumber(value: MetricValue, fallback: string = UNMEASURED): string {
  return isMeasured(value) ? `${round1(value)}` : fallback;
}

/** A 0..1 score as two decimals. A missing score is not 0.00 and not 1.00. */
export function formatScore(value: MetricValue, fallback: string = UNMEASURED): string {
  return isMeasured(value) ? value.toFixed(2) : fallback;
}

/** Keeps the sub-millisecond noise out without inventing precision. */
function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

/** Only the finite numbers, so an aggregate is never computed over holes. */
export function measuredOnly(values: readonly MetricValue[]): number[] {
  return values.filter(isMeasured);
}

/**
 * Why the STT tile may read `not measured` for an entire consultation.
 *
 * docs/00-HANDOVER §6: the only STT measurement unmute emits is
 * `request_duration`, emitted as `None if metric.streamed` — and Saaras streams,
 * so it is *always* unavailable. The number actually wanted is
 * `transcription_delay` from EOUMetrics, which the console looks for as well
 * (`console/app/metrics.py:METRIC_ALIASES`). If neither is in the log the tile
 * stays empty, and that is correct behaviour rather than a bug to paper over
 * with a zero.
 */
export const STT_STAGE_NOTE =
  "Saaras streams, so STT request_duration is always unavailable; this tile fills " +
  "only from EOU transcription_delay. Empty here means no sample, not a fast STT.";

export const NO_SAMPLES_NOTE =
  "No turn has been measured yet. Nothing on this panel is estimated, defaulted or filled in — " +
  "a tile is blank exactly when the measurement is missing.";
