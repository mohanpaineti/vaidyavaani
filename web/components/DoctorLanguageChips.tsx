"use client";

/** Doctor side defaults to English, switchable from a chip (docs/01 §1). */

const DOCTOR_LANGS = [
  { lang: "en", label: "EN" },
  { lang: "hi", label: "HI" },
  { lang: "kn", label: "KN" },
  { lang: "ta", label: "TA" },
];

export function DoctorLanguageChips({
  current,
  onPick,
}: {
  current: string;
  onPick: (lang: string) => void;
}) {
  return (
    <span className="flex items-center gap-1">
      {DOCTOR_LANGS.map((l) => (
        <button
          key={l.lang}
          type="button"
          onClick={() => onPick(l.lang)}
          className={[
            "rounded-full border px-2 py-0.5 text-[11px] font-semibold",
            current === l.lang
              ? "border-emerald-400 bg-emerald-800/40 text-emerald-100"
              : "border-slate-700 text-slate-400 hover:bg-slate-800",
          ].join(" ")}
        >
          {l.label}
        </button>
      ))}
    </span>
  );
}
