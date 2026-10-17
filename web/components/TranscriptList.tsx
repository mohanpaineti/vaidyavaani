"use client";

/**
 * The doctor's transcript: ENGLISH TRANSLATION ABOVE the original-language
 * transcript, always (docs/01 §2). That ordering is the whole point — a doctor
 * who speaks neither language can still see an invented or dropped phrase by
 * comparing the two lines, and length mismatch is visible at a glance.
 */

import { useEffect, useRef } from "react";
import type { Side, Turn } from "@/lib/types";

export interface TranscriptListProps {
  turns: Turn[];
  partials: Partial<Record<Side, string>>;
  patientFontClass: string;
}

export function TranscriptList({ turns, partials, patientFontClass }: TranscriptListProps) {
  const endRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [turns.length, partials.patient, partials.doctor]);

  return (
    <div
      aria-label="Transcript"
      className="min-h-[8rem] space-y-3 overflow-y-auto rounded-lg border border-slate-800 bg-slate-900/40 p-3"
    >
      {turns.length === 0 && !partials.patient && !partials.doctor ? (
        <p className="text-sm text-slate-500">
          No turns yet. Hold a button and speak; release ends the turn.
        </p>
      ) : null}

      {turns.map((turn) => (
        <article key={turn.id} className="border-b border-slate-800 pb-2 last:border-0">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-slate-500">
            <span
              className={
                turn.side === "patient"
                  ? "font-bold text-sky-300"
                  : turn.side === "doctor"
                    ? "font-bold text-emerald-300"
                    : "font-bold text-slate-400"
              }
            >
              {turn.side}
            </span>
            <span className="font-mono">{turn.detected_language}</span>
            <span className="ml-auto font-mono">{timeOf(turn.at)}</span>
          </div>

          {/* EN first, deliberately. */}
          <p className="mt-1 text-base leading-snug">
            <span className="mr-2 font-mono text-xs text-slate-500">EN</span>
            {turn.english_text}
          </p>
          <p className={`mt-0.5 text-sm leading-snug text-slate-400 ${patientFontClass}`}>
            <span className="mr-2 font-mono text-xs text-slate-600">
              {turn.detected_language}
            </span>
            {turn.original_text}
          </p>

          {turn.lay_terms.length > 0 ? (
            <p className="mt-1 text-xs text-amber-200">
              lay terms:{" "}
              {turn.lay_terms
                .map((t) => `“${t.said}” → ${t.likely_means}`)
                .join(" · ")}
            </p>
          ) : null}
          {turn.negations.length > 0 ? (
            <p className="mt-1 text-xs text-sky-200">
              negations: {turn.negations.map((n) => `“${n}”`).join(" · ")}
            </p>
          ) : null}
        </article>
      ))}

      {(["patient", "doctor"] as const).map((side) =>
        partials[side] ? (
          <p key={side} className="text-sm italic text-slate-500">
            <span className="mr-2 font-mono text-xs uppercase">{side} …</span>
            {partials[side]}
          </p>
        ) : null,
      )}
      <div ref={endRef} />
    </div>
  );
}

function timeOf(at: string): string {
  const d = new Date(at);
  return Number.isNaN(d.getTime()) ? "" : d.toISOString().slice(11, 19);
}
