"use client";

/**
 * Red flags, docs/01 §3. Doctor's half ONLY, in English, with the original
 * phrase quoted. The patient half never shows or speaks anything about these,
 * and the app never advises — it just puts the phrase in front of the doctor.
 */

import type { RedFlag } from "@/lib/types";

export function RedFlagList({ flags }: { flags: RedFlag[] }) {
  if (flags.length === 0) return null;
  const ordered = [...flags].sort((a, b) =>
    a.severity === b.severity ? 0 : a.severity === "urgent" ? -1 : 1,
  );

  return (
    <section aria-label="Red flags" className="space-y-2">
      {ordered.map((flag) => (
        <div
          key={flag.id}
          role="alert"
          className={[
            "rounded-lg border-l-8 px-3 py-2",
            flag.severity === "urgent"
              ? "border-flag bg-flag/25 text-red-50"
              : "border-amber-500 bg-amber-900/25 text-amber-50",
          ].join(" ")}
        >
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="text-base font-extrabold uppercase tracking-wide">
              🚩 {flag.severity === "urgent" ? "Red flag" : "Watch"}
            </span>
            <span className="text-base font-semibold">{flag.english}</span>
            <span className="ml-auto text-[11px] uppercase tracking-wider opacity-70">
              {flag.source}
            </span>
          </div>
          {/* The original phrase, quoted — so the doctor sees what was actually said. */}
          <p className="mt-1 text-sm opacity-90">
            patient said: <span className="font-semibold">&ldquo;{flag.phrase}&rdquo;</span>
          </p>
        </div>
      ))}
    </section>
  );
}
