"use client";

/**
 * The whole product: one screen, two halves (docs/01 §2).
 *
 * On a phone the halves stack, patient first — a phone is the fallback device,
 * and the patient's half is the one that must never be scrolled away from. On a
 * tablet in landscape they sit side by side. Nothing scrolls horizontally at any
 * width.
 */

import { PatientPanel } from "@/components/PatientPanel";
import { DoctorPanel } from "@/components/DoctorPanel";
import { SessionHeader } from "@/components/SessionHeader";
import { useSession } from "@/hooks/useSession";

export default function Page() {
  const s = useSession();
  const state = s.view.state;

  return (
    <main className="flex min-h-screen w-full flex-col">
      <SessionHeader
        state={state}
        connection={s.view.connection}
        audioJoined={s.audioJoined}
        lastLatency={state?.metrics.last_reply_latency_ms ?? null}
        onSetLanguage={(side, lang) => void s.setLanguage(side, lang)}
        onSetConsent={(given) => void s.setConsent(given)}
        onEnd={() => void s.endSession()}
      />

      {!state ? (
        <StartScreen
          starting={s.starting}
          error={s.startError}
          connection={s.view.connection}
          onStart={() => void s.start()}
        />
      ) : (
        <div className="flex flex-1 flex-col lg:flex-row">
          <PatientPanel
            language={state.patient_language}
            turns={state.turns}
            partials={s.view.partials}
            prescription={state.prescription}
            voiceNote={state.voice_note}
            readback={s.view.readback}
            holding={s.holding}
            agentSpeaking={s.agentSpeaking}
            onPress={() => s.pressPtt("patient")}
            onRelease={() => s.releasePtt("patient")}
          />
          <DoctorPanel
            state={state}
            view={s.view}
            metrics={s.view.metrics}
            failovers={s.view.failovers}
            holding={s.holding}
            gateRefusal={s.gateRefusal}
            onPress={() => s.pressPtt("doctor")}
            onRelease={() => s.releasePtt("doctor")}
            onPatch={(lineId, patch) => void s.patchLine(lineId, patch)}
            onConfirmLine={(lineId) => void s.confirmLine(lineId)}
            onConfirmAll={() => void s.confirmAll()}
            onReject={() => void s.rejectRx()}
            onSetLanguage={(side, lang) => void s.setLanguage(side, lang)}
          />
        </div>
      )}

      {s.view.endedReason ? (
        <p className="border-t border-slate-800 px-3 py-2 text-xs text-slate-400">
          Session ended — {s.view.endedReason}
        </p>
      ) : null}
    </main>
  );
}

/**
 * Staff tap one button to begin. The mic is not opened here: the browser's
 * permission prompt lands on the first push-to-talk press, which is also the
 * gesture that unblocks audio autoplay.
 */
function StartScreen({
  starting,
  error,
  connection,
  onStart,
}: {
  starting: boolean;
  error: string | null;
  connection: string;
  onStart: () => void;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 p-6 text-center">
      <div>
        <h1 className="text-3xl font-extrabold">VaidyaVaani</h1>
        <p className="mt-2 max-w-md text-slate-400">
          The patient speaks their language, the doctor works in English, and no dose is
          spoken to anyone until the doctor has confirmed it on screen.
        </p>
      </div>

      <button
        type="button"
        onClick={onStart}
        disabled={starting}
        className="rounded-2xl border-4 border-sky-400 bg-sky-700/40 px-10 py-7 text-2xl font-extrabold uppercase tracking-wider hover:bg-sky-700/60 disabled:opacity-50"
      >
        {starting ? "Starting…" : "Start consultation"}
      </button>

      {error ? (
        <div role="alert" className="max-w-lg rounded border border-red-800 bg-flag/20 p-3 text-sm">
          <p className="font-bold">Could not reach the console.</p>
          <p className="mt-1 font-mono text-xs text-red-200">{error}</p>
          <p className="mt-2 text-slate-300">
            Start the real console, or the dev stub: <code>npm run mock</code>
          </p>
        </div>
      ) : null}

      <p className="text-xs text-slate-600">ws {connection}</p>
    </div>
  );
}
