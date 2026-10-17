"use client";

/** The one-line status bar from the ASCII layout in docs/01 §2. */

import { LANGUAGE_CHIPS, stringsFor } from "@/lib/i18n";
import {
  BAND_CLASS,
  UNMEASURED_SHORT,
  UNMEASURED_CLASS,
  bandFor,
  formatNumber,
} from "@/lib/metrics-format";
import type { ConnectionStatus } from "@/lib/console-ws";
import type { PatientLanguage, SessionState, Stage } from "@/lib/types";

const STAGE_LABEL: Record<Stage, string> = {
  start: "1 start",
  consent: "1 consent",
  interpret: "2 interpret",
  prescribe: "4 prescribe",
  await_confirm: "4b awaiting doctor",
  readback: "5 read-back",
  teachback: "5 teach-back",
  takehome: "6 take it home",
  ended: "ended",
};

export function SessionHeader({
  state,
  connection,
  audioJoined,
  lastLatency,
  onSetLanguage,
  onSetConsent,
  onEnd,
}: {
  state: SessionState | null;
  connection: ConnectionStatus;
  audioJoined: boolean;
  lastLatency: number | null;
  onSetLanguage: (side: "patient" | "doctor", lang: string) => void;
  onSetConsent: (given: boolean) => void;
  onEnd: () => void;
}) {
  const lang = (state?.patient_language ?? "") as PatientLanguage;
  const t = stringsFor(lang);
  const consentGiven = state?.consent?.given ?? null;

  return (
    <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-slate-800 bg-slate-900/80 px-3 py-2 text-xs">
      <span className="text-sm font-extrabold tracking-wide text-sky-300">VaidyaVaani</span>

      <span className="font-mono text-slate-400">{state?.session_id ?? "no session"}</span>

      <span className="rounded bg-slate-800 px-2 py-0.5 font-semibold">
        {lang ? `${t.label} ⇄ ${(state?.doctor_language ?? "en").toUpperCase()}` : "language?"}
      </span>

      <span className="rounded px-2 py-0.5 font-semibold text-slate-200">
        {STAGE_LABEL[state?.stage ?? "start"]}
      </span>

      {/* Consent. Declining is a first-class path, not an error (docs/01 §1). */}
      {consentGiven === true ? (
        <span className="text-emerald-300">● consent given</span>
      ) : consentGiven === false ? (
        <span className="rounded bg-amber-900/50 px-2 py-0.5 text-amber-200">
          consent declined — interpretation only, no transcript kept
        </span>
      ) : (
        <span className="flex items-center gap-1 text-slate-400">
          ○ consent pending
          <button
            type="button"
            onClick={() => onSetConsent(true)}
            className="rounded border border-slate-600 px-1.5 py-0.5 hover:bg-slate-800"
          >
            yes
          </button>
          <button
            type="button"
            onClick={() => onSetConsent(false)}
            className="rounded border border-slate-600 px-1.5 py-0.5 hover:bg-slate-800"
          >
            no
          </button>
        </span>
      )}

      {/* One-tap language override — Telugu heard as Kannada must be one tap to fix. */}
      <span className="flex items-center gap-1">
        {LANGUAGE_CHIPS.map((chip) => (
          <button
            key={chip.lang}
            type="button"
            onClick={() => onSetLanguage("patient", chip.lang)}
            className={[
              "rounded-full border px-2 py-0.5",
              lang === chip.lang
                ? "border-sky-400 bg-sky-700/50 text-sky-50"
                : "border-slate-700 text-slate-300 hover:bg-slate-800",
            ].join(" ")}
          >
            {chip.native}
          </button>
        ))}
      </span>

      <span className="ml-auto flex items-center gap-3">
        {/* The bolt is a *measurement*. With no measurement there is no bolt and
            no colour — the old chain ended in `text-red-300` as its else, so a
            null latency rendered a red "ms" chip for a turn nobody timed, and a
            0 rendered an emerald "0ms". Both were verdicts on nothing. */}
        <LatencyChip ms={lastLatency} />
        <span className={audioJoined ? "text-emerald-300" : "text-slate-500"}>
          {audioJoined ? "🎧 audio" : "🎧 no audio"}
        </span>
        <span
          className={
            connection === "open"
              ? "text-emerald-300"
              : connection === "reconnecting"
                ? "text-amber-300"
                : "text-slate-500"
          }
        >
          ws {connection}
        </span>
        <button
          type="button"
          onClick={onEnd}
          className="rounded border border-slate-600 px-2 py-0.5 text-slate-300 hover:bg-slate-800"
        >
          End
        </button>
      </span>
    </header>
  );
}

/**
 * The header's one-glance latency. Shown only when there is something to show;
 * a frame that carried no timing says so in slate rather than borrowing a band
 * colour. `bandFor` returns `Band | null`, and `BAND_CLASS` is keyed by `Band`,
 * so the unmeasured arm cannot be dropped without a type error.
 */
function LatencyChip({ ms }: { ms: number | null }) {
  const band = bandFor(ms);
  if (band === null) {
    return (
      <span className={`font-mono tabular-nums ${UNMEASURED_CLASS}`} title="no reply latency measured yet">
        ⚡ {UNMEASURED_SHORT}
      </span>
    );
  }
  return (
    <span className="font-mono tabular-nums">
      ⚡ <span className={BAND_CLASS[band]}>{formatNumber(ms)}ms</span>
    </span>
  );
}
