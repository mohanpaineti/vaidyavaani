"use client";

/**
 * Live latency panel, docs/01 F10. Reply latency and stage timings come from the
 * `metric` frame; the rating bands are LiveKit's own:
 *
 *   ≤ 900 ms      good
 *   900–1200 ms   slow
 *   > 1200 ms     over limit
 *
 * **This panel never shows a number it was not given.** Not as 0, not as 0 ms,
 * not as a green band. Every value is routed through `lib/metrics-format.ts`,
 * whose `bandFor` returns `null` for anything unmeasured and whose colour tables
 * are keyed by `Band` — so a future edit that forgets the unmeasured case fails
 * to compile rather than painting an untimed turn green on stage.
 *
 * The counts in the heading are deliberately two numbers, not one: frames
 * received and frames carrying a latency. When they differ, the gap is the
 * honest story, and burying it would be the whole failure mode this panel
 * exists to avoid.
 *
 * `failover` frames are shown prominently and kept — killing a provider mid-call
 * is a demo beat (F11), and the gap in ms is the number worth showing a judge.
 */

import type { FailoverEvent, MetricSample } from "@/lib/console-ws";
import { p90 } from "@/lib/console-ws";
import {
  BAND_BAR_CLASS,
  BAND_CLASS,
  BAND_GOOD_MS,
  BAND_LABEL,
  BAND_LIMIT_MS,
  NO_SAMPLES_NOTE,
  STT_STAGE_NOTE,
  UNMEASURED,
  UNMEASURED_CLASS,
  bandFor,
  formatMs,
  formatNumber,
  isMeasured,
  measuredOnly,
} from "@/lib/metrics-format";
import type { MetricValue } from "@/lib/metrics-format";

export { BAND_GOOD_MS, BAND_LIMIT_MS, bandFor } from "@/lib/metrics-format";
export type { Band } from "@/lib/metrics-format";

export function MetricsHUD({
  metrics,
  failovers,
}: {
  metrics: MetricSample[];
  failovers: FailoverEvent[];
}) {
  const last = metrics.length > 0 ? metrics[metrics.length - 1] : null;
  const values = metrics.map((m) => m.reply_latency_ms);
  const measured = measuredOnly(values);
  const median = medianOf(measured);
  const worst = measured.length > 0 ? Math.max(...measured) : null;
  const p90ms = p90(values);

  const lastBand = bandFor(last?.reply_latency_ms);

  return (
    <section
      aria-label="Latency"
      className="rounded-lg border border-slate-800 bg-slate-900/50 p-3"
    >
      <h2 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-400">
        Latency · {metrics.length} turn{metrics.length === 1 ? "" : "s"}
        {/* Two counts, not one: a turn we failed to time is not a turn we timed fast. */}
        {metrics.length > 0 && measured.length !== metrics.length ? (
          <span className="ml-1 font-normal normal-case tracking-normal text-amber-300">
            · {measured.length} measured, {metrics.length - measured.length} without a timing
          </span>
        ) : null}
      </h2>

      {last ? (
        <>
          <div className="flex items-end gap-4">
            <div>
              {lastBand ? (
                <p
                  className={`font-mono text-3xl font-bold tabular-nums ${BAND_CLASS[lastBand]}`}
                  data-testid="last-reply"
                >
                  {formatNumber(last.reply_latency_ms)}
                  <span className="ml-1 text-sm font-normal">ms</span>
                </p>
              ) : (
                /* No unit, no digits, no colour that could read as a verdict. */
                <p
                  className={`text-xl font-bold ${UNMEASURED_CLASS}`}
                  data-testid="last-reply"
                >
                  {UNMEASURED}
                </p>
              )}
              <p className="text-[11px] uppercase tracking-wider text-slate-500">
                last reply · {lastBand ? BAND_LABEL[lastBand] : "no timing in this frame"}
              </p>
            </div>
            <dl className="grid grid-cols-3 gap-x-3 text-xs">
              <Stat label="median" value={median} />
              <Stat label="p90" value={p90ms} />
              <Stat label="worst" value={worst} />
            </dl>
          </div>

          <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
            <Stage label="STT" ms={last.stages.stt} note={STT_STAGE_NOTE} />
            <Stage label="LLM ttft" ms={last.stages.llm_ttft} />
            <Stage label="TTS 1st" ms={last.stages.tts_first_audio} />
          </dl>

          {/* Sparkline: a glance tells you whether it is drifting upward. An
              unmeasured turn is a hollow slot, not a short green bar. */}
          <div className="mt-3 flex h-10 items-end gap-0.5" aria-hidden>
            {metrics.slice(-24).map((m, i) => {
              const b = bandFor(m.reply_latency_ms);
              if (b === null || !isMeasured(m.reply_latency_ms)) {
                return (
                  <span
                    key={i}
                    className="h-full w-1.5 rounded-sm border border-dashed border-slate-700"
                  />
                );
              }
              const h = Math.max(6, Math.min(100, (m.reply_latency_ms / 2000) * 100));
              return (
                <span
                  key={i}
                  style={{ height: `${h}%` }}
                  className={`w-1.5 rounded-sm ${BAND_BAR_CLASS[b]}`}
                />
              );
            })}
          </div>
          <p className="mt-1 text-[10px] text-slate-500">
            bands: ≤{BAND_GOOD_MS}ms good · ≤{BAND_LIMIT_MS}ms slow · above that over limit ·
            a dashed slot is a turn with no timing
          </p>
        </>
      ) : (
        <p className="text-sm text-slate-500" data-testid="no-samples">
          {NO_SAMPLES_NOTE}
        </p>
      )}

      {failovers.map((f, i) => (
        <div
          key={i}
          role="status"
          className="mt-3 rounded border-l-4 border-amber-400 bg-amber-900/30 px-2 py-1.5 text-xs text-amber-100"
        >
          <span className="font-bold uppercase tracking-wider">⚡ Failover </span>
          <span className="font-mono">{f.from}</span> → <span className="font-mono">{f.to}</span>
          <span className="ml-1 font-mono tabular-nums">
            · gap {formatMs(f.gap_ms, `${UNMEASURED}`)}
          </span>
          <span className="ml-1 opacity-80">· call continued</span>
        </div>
      ))}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: MetricValue }) {
  const measured = isMeasured(value);
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-slate-500">{label}</dt>
      <dd
        className={`font-mono tabular-nums ${measured ? "text-slate-200" : UNMEASURED_CLASS}`}
        data-testid={`stat-${label}`}
      >
        {formatNumber(value)}
      </dd>
    </div>
  );
}

/**
 * One stage tile. `undefined` (key omitted by the console) and `null` (key
 * present, no value) mean the same thing on screen and must: we do not have it.
 */
function Stage({ label, ms, note }: { label: string; ms: MetricValue; note?: string }) {
  const measured = isMeasured(ms);
  return (
    <div className="rounded bg-slate-950/60 px-2 py-1" title={measured ? undefined : note}>
      <dt className="text-[10px] uppercase tracking-wider text-slate-500">{label}</dt>
      <dd
        className={`font-mono tabular-nums ${measured ? "text-slate-200" : UNMEASURED_CLASS}`}
        data-testid={`stage-${label}`}
      >
        {formatMs(ms)}
      </dd>
    </div>
  );
}

function medianOf(values: number[]): number | null {
  if (values.length === 0) return null;
  const s = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : Math.round((s[mid - 1] + s[mid]) / 2);
}
