"use client";

/**
 * The patient's half (docs/01 §2). Everything here is 24pt or more, in the
 * patient's own script, with icons carrying the meaning for non-readers. One
 * button. No login, no text input, nothing else tappable during a turn.
 *
 * Red flags never appear here, by construction — this component is not given
 * them.
 */

import { stringsFor } from "@/lib/i18n";
import { PushToTalkButton } from "./PushToTalkButton";
import { PictureCard } from "./PictureCard";
import { QrPanel } from "./QrPanel";
import type { PttSide } from "@/lib/push-to-talk";
import type { PatientLanguage, Prescription, Side, Turn, VoiceNote } from "@/lib/types";

export interface PatientPanelProps {
  language: PatientLanguage;
  turns: Turn[];
  partials: Partial<Record<Side, string>>;
  prescription: Prescription;
  voiceNote: VoiceNote | null;
  /** The exact read-back string, shown in large type while it is spoken. */
  readback: { text: string; language: string } | null;
  holding: PttSide | null;
  agentSpeaking: boolean;
  onPress: () => void;
  onRelease: () => void;
}

export function PatientPanel({
  language,
  turns,
  partials,
  prescription,
  voiceNote,
  readback,
  holding,
  agentSpeaking,
  onPress,
  onRelease,
}: PatientPanelProps) {
  const t = stringsFor(language);
  /**
   * Only turns that exist in the patient's own language may show here: their own
   * words, or the agent's interpretation of the doctor. A doctor turn's
   * `original_text` is English — putting that in front of a low-literacy patient
   * is worse than showing nothing, so it is deliberately skipped and the agent
   * turn that follows it is what they read.
   */
  const lastForPatient = [...turns]
    .reverse()
    .find((turn) => turn.side === "patient" || turn.side === "agent");

  const bigText = partials.patient ?? readback?.text ?? lastForPatient?.original_text ?? "";

  return (
    <section
      aria-label="Patient side"
      className="flex flex-col gap-4 border-slate-800 p-4 lg:w-1/2 lg:border-r"
    >
      <div className={`min-h-[8rem] rounded-2xl bg-slate-900/60 p-4 ${t.fontClass}`}>
        {bigText ? (
          <p className="text-patient-lg font-semibold leading-snug">{bigText}</p>
        ) : (
          <p className="text-patient text-slate-500">{t.waitingForDoctor}</p>
        )}
      </div>

      <p
        className={`text-patient font-bold ${t.fontClass} ${
          holding === "patient"
            ? "text-red-300"
            : agentSpeaking
              ? "text-sky-300"
              : "text-transparent"
        }`}
        aria-live="polite"
      >
        {holding === "patient" ? t.listening : agentSpeaking ? t.agentSpeaking : "·"}
      </p>

      <PushToTalkButton
        side="patient"
        size="patient"
        label={t.label === "English" ? "PATIENT — HOLD TO TALK" : "PATIENT"}
        sublabel={t.holdToTalk}
        fontClass={t.fontClass}
        held={holding === "patient"}
        disabled={holding === "doctor"}
        onPress={onPress}
        onRelease={onRelease}
      />

      {/* Only confirmed lines reach the patient's eyes. */}
      <PictureCard lines={prescription.lines} language={language} />
      <QrPanel voiceNote={voiceNote} language={language} />
    </section>
  );
}
