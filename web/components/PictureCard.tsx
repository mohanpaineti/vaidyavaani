"use client";

/**
 * The take-home picture card, docs/01 §6. It has to work for someone who cannot
 * read at all, so meaning is carried by: ☀/🌙 icons for time of day, a repeated
 * tablet glyph for the count (not a numeral alone — "2" is a reading task), a
 * plate icon for before/after food, and a strip of day boxes.
 *
 * It renders only from CONFIRMED lines: nothing unconfirmed may reach the
 * patient's eyes any more than their ears. Printable — see `@media print`.
 */

import { stringsFor, type PatientStrings } from "@/lib/i18n";
import { doseDigits, splitDose, strengthDigits } from "@/lib/rx";
import type { PatientLanguage, RxForm, RxLine } from "@/lib/types";

/** A syrup is not a tablet. The glyph and the word both follow `form`. */
function doseGlyph(form: RxForm): string {
  switch (form) {
    case "syrup":
      return "🥄";
    case "drops":
      return "💧";
    case "injection":
      return "💉";
    case "ointment":
      return "🧴";
    default:
      return "⚪";
  }
}

function doseWord(form: RxForm, t: PatientStrings): string {
  switch (form) {
    case "syrup":
      return t.spoon;
    case "drops":
      return t.drop;
    case "injection":
      return t.injection;
    default:
      return t.tablet;
  }
}

/**
 * A whole tablet, drawn rather than an emoji so the half below is visibly the
 * SAME object cut in two.
 *
 * Deliberately NO score line down the middle: at glyph size a score line is the
 * one thing that reads like the half's cut edge, and whole-vs-half is the single
 * distinction this card exists to make.
 */
function WholeTablet({ size = 40 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden focusable="false">
      <circle cx="20" cy="20" r="17" fill="#fff" stroke="#1f2937" strokeWidth="2.5" />
    </svg>
  );
}

/**
 * Half a tablet: the same circle with the right half gone and a flat cut edge.
 * This glyph is the ONLY representation of a half dose a non-reader can use —
 * the `0.5` beside it is for whoever can read, not for them.
 */
function HalfTablet({ size = 40 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden focusable="false">
      {/* Ghost of the missing half, so it reads as "half of one", not "a small one". */}
      <circle
        cx="20"
        cy="20"
        r="17"
        fill="none"
        stroke="#d1d5db"
        strokeWidth="2"
        strokeDasharray="3 3"
      />
      <path
        d="M20 3 A17 17 0 0 0 20 37 Z"
        fill="#cbd5e1"
        stroke="#1f2937"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

const SLOTS = [
  { key: "morning", icon: "☀️" },
  { key: "afternoon", icon: "🌤️" },
  { key: "night", icon: "🌙" },
] as const;

export function PictureCard({
  lines,
  language,
}: {
  lines: RxLine[];
  language: PatientLanguage;
}) {
  const t = stringsFor(language);
  const confirmed = lines.filter((l) => l.confirmed);
  if (confirmed.length === 0) return null;

  return (
    <section
      aria-label="Medicine picture card"
      className={`rounded-2xl border-4 border-slate-600 bg-white p-4 text-slate-900 ${t.fontClass}`}
    >
      <h2 className="mb-3 text-patient font-bold">{t.yourMedicines}</h2>
      <ul className="space-y-4">
        {confirmed.map((line) => (
          <li key={line.id} className="rounded-xl border-2 border-slate-300 p-3">
            <p className="text-patient font-bold">{line.drug_text}</p>
            {/* Never spoken in the read-back (docs/04 §2 rulings) — this card and
                the doctor's card are the only places the strength appears. */}
            {line.strength_value !== null ? (
              <p className="mb-2 font-mono text-3xl font-bold tabular-nums text-slate-700">
                {strengthDigits(line)}
              </p>
            ) : (
              <div className="mb-2" />
            )}

            <div className="flex flex-wrap gap-4">
              {SLOTS.map(({ key, icon }) => {
                const count = line.schedule[key];
                if (count === 0) return null;
                const { whole, half } = splitDose(count);
                const isTablet = line.form === "tablet" || line.form === "capsule" || line.form === null;
                return (
                  <div key={key} className="flex items-center gap-2">
                    <span aria-hidden className="text-5xl leading-none">
                      {icon}
                    </span>
                    <span className="flex items-center gap-1">
                      {/* One glyph per unit, plus a half glyph for a half dose:
                          countable without reading a numeral at all. */}
                      {Array.from({ length: whole }).map((_, i) =>
                        isTablet ? (
                          <WholeTablet key={i} />
                        ) : (
                          <span key={i} aria-hidden className="text-4xl leading-none">
                            {doseGlyph(line.form)}
                          </span>
                        ),
                      )}
                      {half ? (
                        isTablet ? (
                          <HalfTablet />
                        ) : (
                          <span aria-hidden className="flex items-center text-4xl leading-none">
                            <span className="opacity-60">{doseGlyph(line.form)}</span>
                            <span className="ml-0.5 text-3xl font-bold">½</span>
                          </span>
                        )
                      ) : null}
                      <span className="ml-1 text-patient font-bold tabular-nums">
                        {doseDigits(count)}
                      </span>
                    </span>
                    <span className="sr-only">
                      {t[key]}: {half && whole === 0 ? t.half : doseDigits(count)}{" "}
                      {doseWord(line.form, t)}
                    </span>
                  </div>
                );
              })}
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-5">
              {line.food_relation ? (
                <span className="flex items-center gap-2">
                  <span aria-hidden className="text-5xl leading-none">
                    🍽️
                  </span>
                  <span aria-hidden className="text-4xl leading-none">
                    {line.food_relation === "before_food" ? "⬅️" : line.food_relation === "after_food" ? "➡️" : "🔄"}
                  </span>
                  <span className="text-2xl font-semibold">
                    {line.food_relation === "before_food"
                      ? t.beforeFood
                      : line.food_relation === "after_food"
                        ? t.afterFood
                        : t.withFood}
                  </span>
                </span>
              ) : null}
            </div>

            {line.duration_days ? (
              <div className="mt-3">
                <div className="flex flex-wrap gap-1.5">
                  {/* A box per day, up to a strip that still fits a phone. */}
                  {Array.from({ length: Math.min(line.duration_days, 14) }).map((_, i) => (
                    <span
                      key={i}
                      aria-hidden
                      className="inline-flex h-10 w-10 items-center justify-center rounded border-2 border-slate-400 text-lg font-bold tabular-nums"
                    >
                      {i + 1}
                    </span>
                  ))}
                  {line.duration_days > 14 ? (
                    <span className="self-center text-2xl font-bold tabular-nums">
                      +{line.duration_days - 14}
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 text-2xl font-semibold tabular-nums">
                  {line.duration_days} {t.days}
                </p>
              </div>
            ) : null}
          </li>
        ))}
      </ul>

      <button
        type="button"
        onClick={() => window.print()}
        className="no-print mt-4 w-full rounded-lg border-2 border-slate-400 px-3 py-2 text-base font-semibold"
      >
        🖨 Print
      </button>
    </section>
  );
}
