"use client";

/**
 * The doctor's half (docs/01 §2): dense English, EN translation above the
 * original transcript, red flags in English with the phrase quoted, the
 * prescription card, the latency HUD, and the doctor's own push-to-talk.
 */

import { stringsFor } from "@/lib/i18n";
import { DoctorLanguageChips } from "./DoctorLanguageChips";
import { MetricsHUD } from "./MetricsHUD";
import { PrescriptionCard } from "./PrescriptionCard";
import { PushToTalkButton } from "./PushToTalkButton";
import { RedFlagList } from "./RedFlagList";
import { TeachBackPanel } from "./TeachBackPanel";
import { TranscriptList } from "./TranscriptList";
import type { ConsoleView, FailoverEvent, MetricSample } from "@/lib/console-ws";
import type { PttSide } from "@/lib/push-to-talk";
import type { RxLine, SessionState } from "@/lib/types";

export interface DoctorPanelProps {
  state: SessionState;
  view: ConsoleView;
  metrics: MetricSample[];
  failovers: FailoverEvent[];
  holding: PttSide | null;
  gateRefusal: string | null;
  onPress: () => void;
  onRelease: () => void;
  onPatch: (lineId: string, patch: Partial<RxLine>) => void;
  onConfirmLine: (lineId: string) => void;
  onConfirmAll: () => void;
  onReject: () => void;
  onSetLanguage: (side: "patient" | "doctor", lang: string) => void;
}

export function DoctorPanel({
  state,
  view,
  metrics,
  failovers,
  holding,
  gateRefusal,
  onPress,
  onRelease,
  onPatch,
  onConfirmLine,
  onConfirmAll,
  onReject,
  onSetLanguage,
}: DoctorPanelProps) {
  const patientFont = stringsFor(state.patient_language).fontClass;

  return (
    <section
      aria-label="Doctor side"
      className="flex flex-col gap-3 p-3 text-sm lg:w-1/2"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-xs font-bold uppercase tracking-widest text-slate-400">
          Doctor
        </h2>
        <DoctorLanguageChips
          current={state.doctor_language}
          onPick={(lang) => onSetLanguage("doctor", lang)}
        />
      </div>

      {/* Doctor's half only, English, phrase quoted. Never the patient's. */}
      <RedFlagList flags={state.red_flags} />

      {view.errors.length > 0 ? (
        <div role="alert" className="rounded border border-red-800 bg-flag/20 px-2 py-1 text-xs">
          {view.errors.map((e, i) => (
            <p key={i}>
              <span className="font-mono">{e.code}</span> · {e.message}
            </p>
          ))}
        </div>
      ) : null}

      <TranscriptList
        turns={state.turns}
        partials={view.partials}
        patientFontClass={patientFont}
      />

      {view.readback ? (
        <div className="rounded border border-sky-800 bg-sky-950/40 px-2 py-1.5 text-xs">
          <span className="font-bold uppercase tracking-wider text-sky-300">
            Read-back spoken
          </span>{" "}
          <span className="font-mono text-slate-400">({view.readback.language})</span>
          <p className={`mt-1 text-base ${patientFont}`}>{view.readback.text}</p>
          <p className="mt-1 text-[11px] text-slate-500">
            Rendered by the console from the confirmed fields — not translated by a model.
          </p>
        </div>
      ) : null}

      <TeachBackPanel
        result={state.teachback}
        drugNameFor={(lineId) =>
          state.prescription.lines.find((l) => l.id === lineId)?.drug_text ?? lineId
        }
      />

      <PrescriptionCard
        prescription={state.prescription}
        ambiguities={view.ambiguities}
        gateRefusal={gateRefusal}
        onPatch={onPatch}
        onConfirmLine={onConfirmLine}
        onConfirmAll={onConfirmAll}
        onReject={onReject}
      />

      <MetricsHUD metrics={metrics} failovers={failovers} />

      <PushToTalkButton
        side="doctor"
        size="doctor"
        label="Doctor — hold to talk"
        held={holding === "doctor"}
        disabled={holding === "patient"}
        onPress={onPress}
        onRelease={onRelease}
      />
    </section>
  );
}
