"use client";

/**
 * Teach-back, docs/01 §5. Every verdict here was computed in Python by the
 * console — numbers compared arithmetically, not semantically (docs/04 §2). This
 * component only renders them, field by field, on the doctor's half.
 */

import type { TeachBackResult, TeachBackVerdict } from "@/lib/types";

const MARK: Record<TeachBackVerdict, string> = {
  match: "✓",
  mismatch: "✗",
  not_mentioned: "–",
};

const MARK_CLASS: Record<TeachBackVerdict, string> = {
  match: "text-emerald-300",
  mismatch: "text-red-300 font-bold",
  not_mentioned: "text-slate-500",
};

export function TeachBackPanel({
  result,
  drugNameFor,
}: {
  result: TeachBackResult | null;
  drugNameFor: (lineId: string) => string;
}) {
  if (!result) return null;

  /*
   * Three outcomes, three looks — and `not_mentioned` is NOT one of the two.
   *
   * A two-way `bad ? red : green` painted `not_mentioned` emerald with the word
   * "not_mentioned" in green beside it: the patient said nothing we could check,
   * rendered as the panel that means they got it right. That is the same
   * zero-for-unknown the latency HUD was guilty of, in the one panel built to
   * catch misunderstanding. An unchecked teach-back is slate and says so.
   */
  const verdict = result.overall;
  const SHELL: Record<TeachBackResult["overall"], string> = {
    mismatch: "border-red-700/70 bg-flag/20",
    match: "border-emerald-800/70 bg-emerald-950/30",
    not_mentioned: "border-slate-700 bg-slate-900/40",
  };
  const WORD: Record<TeachBackResult["overall"], string> = {
    mismatch: "text-red-300",
    match: "text-emerald-300",
    not_mentioned: "text-slate-400",
  };
  const HEADLINE: Record<TeachBackResult["overall"], string> = {
    mismatch: "mismatch",
    match: "match",
    not_mentioned: "nothing to check — the patient did not repeat the dose",
  };

  return (
    <section
      aria-label="Teach-back"
      className={["rounded-lg border px-3 py-2", SHELL[verdict]].join(" ")}
      data-testid={`teachback-${verdict}`}
    >
      <h2 className="text-xs font-bold uppercase tracking-wider text-slate-300">
        Teach-back · <span className={WORD[verdict]}>{HEADLINE[verdict]}</span>
      </h2>

      <ul className="mt-2 space-y-1.5">
        {result.per_line.map((line) => (
          <li key={line.line_id} className="text-sm">
            <span className="font-semibold">{drugNameFor(line.line_id)}</span>
            <span className="ml-2 inline-flex flex-wrap gap-x-3 font-mono">
              <Verdict label="☀ morning" v={line.morning} />
              <Verdict label="🌤 afternoon" v={line.afternoon} />
              <Verdict label="🌙 night" v={line.night} />
              <Verdict label="duration" v={line.duration} />
              <Verdict label="food" v={line.food_relation} />
            </span>
            {Object.keys(line.patient_said).length > 0 ? (
              <span className="ml-2 text-xs text-slate-400">
                patient said {JSON.stringify(line.patient_said)}
              </span>
            ) : null}
          </li>
        ))}
      </ul>

      {result.mismatched_fields.length > 0 ? (
        <p className="mt-2 text-sm text-red-200">
          <span className="font-bold">Mismatched: </span>
          {result.mismatched_fields.join(", ")}
        </p>
      ) : null}
      {result.simplest_restatement ? (
        <p className="mt-1 text-sm text-slate-300">
          <span className="text-slate-500">repeat to patient: </span>
          {result.simplest_restatement}
        </p>
      ) : null}
    </section>
  );
}

function Verdict({ label, v }: { label: string; v: TeachBackVerdict }) {
  return (
    <span className={MARK_CLASS[v]}>
      {label} {MARK[v]}
    </span>
  );
}
