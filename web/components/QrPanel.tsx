"use client";

/**
 * The take-home voice note, docs/01 §6. The console gives us `qr_data_uri` on
 * the `voice_note` frame — we never generate a QR here, because the token in it
 * is short-lived and server-minted.
 *
 * Rendered large: it has to scan from across a desk, from a phone held by
 * someone whose eyes are not good.
 */

import { stringsFor } from "@/lib/i18n";
import type { PatientLanguage, VoiceNote } from "@/lib/types";

export function QrPanel({
  voiceNote,
  language,
}: {
  voiceNote: VoiceNote | null;
  language: PatientLanguage;
}) {
  const t = stringsFor(language);
  if (!voiceNote) return null;

  return (
    <section
      aria-label="Voice note QR code"
      className="rounded-2xl border-4 border-slate-600 bg-white p-4 text-center"
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- a data: URI minted by the console */}
      <img
        src={voiceNote.qr_data_uri}
        alt="QR code to play the voice note"
        className="mx-auto h-56 w-56 sm:h-64 sm:w-64"
      />
      <p className={`mt-3 text-patient font-bold text-slate-900 ${t.fontClass}`}>
        {t.scanForVoiceNote}
      </p>
      <p className="mt-1 font-mono text-xs text-slate-500">{voiceNote.token}</p>
    </section>
  );
}
