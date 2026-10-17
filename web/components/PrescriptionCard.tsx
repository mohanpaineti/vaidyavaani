"use client";

/**
 * The prescription card — the part judges will probe (docs/01 §4).
 *
 * Rules enforced here:
 *   · Doses render as DIGITS, always. `1-0-1`, `500 mg`, `×5d`.
 *   · A line with confidence < 0.8, or any null in a required field, renders
 *     highlighted and CANNOT be confirmed with a single tap — the doctor has to
 *     touch each flagged field (edit it, or explicitly keep it) before the ✓
 *     comes alive.
 *   · CONFIRM & READ BACK is dead until every line is confirmed. The console
 *     answers 409 if we ever get that wrong, so this is belt and braces.
 *   · `ambiguities` from the rx_draft frame show as a banner.
 */

import { useEffect, useMemo, useState } from "react";
import {
  DOSE_MAX,
  DOSE_STEP,
  FIELD_LABEL,
  clampDose,
  confidenceDigits,
  durationDigits,
  fieldsNeedingTouch,
  foodLabel,
  isLowConfidence,
  missingFields,
  needsAttention,
  scheduleDigits,
  strengthDigits,
  totalPerDay,
  type RequiredField,
} from "@/lib/rx";
import type { FoodRelation, Prescription, RxLine, StrengthUnit } from "@/lib/types";

export interface PrescriptionCardProps {
  prescription: Prescription;
  ambiguities: string[];
  gateRefusal: string | null;
  onPatch: (lineId: string, patch: Partial<RxLine>) => void;
  onConfirmLine: (lineId: string) => void;
  onConfirmAll: () => void;
  onReject: () => void;
}

const UNITS: StrengthUnit[] = ["mg", "ml", "g", "iu", "drops", null];
const FOODS: FoodRelation[] = ["before_food", "after_food", "with_food", null];

export function PrescriptionCard({
  prescription,
  ambiguities,
  gateRefusal,
  onPatch,
  onConfirmLine,
  onConfirmAll,
  onReject,
}: PrescriptionCardProps) {
  const { lines } = prescription;
  /** Per line, which flagged fields the doctor has touched this draft. */
  const [touched, setTouched] = useState<Record<string, Set<RequiredField>>>({});

  // A fresh draft for a line wipes its touches: the doctor has to look again.
  const signature = lines.map((l) => `${l.id}:${l.confidence}`).join("|");
  useEffect(() => {
    setTouched({});
  }, [signature]);

  const allConfirmed = lines.length > 0 && lines.every((l) => l.confirmed);
  const locked = prescription.confirmed_at !== null;

  const touch = (lineId: string, field: RequiredField) =>
    setTouched((prev) => {
      const next = new Set(prev[lineId] ?? []);
      next.add(field);
      return { ...prev, [lineId]: next };
    });

  return (
    <section
      aria-label="Prescription"
      className="rounded-xl border border-slate-700 bg-slate-900/60"
    >
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-700 px-3 py-2">
        <h2 className="text-sm font-bold uppercase tracking-wider text-slate-300">
          Prescription{" "}
          <span className={locked ? "text-confirm" : "text-amber-400"}>
            ({locked ? "confirmed" : "unconfirmed"})
          </span>
        </h2>
        <span className="text-xs text-slate-400">
          {lines.filter((l) => l.confirmed).length}/{lines.length} lines confirmed
        </span>
      </header>

      {ambiguities.length > 0 && !locked ? (
        <div
          role="status"
          className="border-b border-amber-700/60 bg-amber-900/30 px-3 py-2 text-sm text-amber-100"
        >
          <span className="font-bold">Ambiguous in dictation: </span>
          {ambiguities.join(" · ")}
        </div>
      ) : null}

      {lines.length === 0 ? (
        <p className="px-3 py-6 text-sm text-slate-500">
          Nothing dictated yet. Hold DOCTOR and dictate the prescription.
        </p>
      ) : (
        <ul className="divide-y divide-slate-800">
          {lines.map((line) => (
            <RxLineRow
              key={line.id}
              line={line}
              locked={locked}
              touched={touched[line.id] ?? new Set()}
              onTouch={(field) => touch(line.id, field)}
              onPatch={(patch) => onPatch(line.id, patch)}
              onConfirm={() => onConfirmLine(line.id)}
            />
          ))}
        </ul>
      )}

      {gateRefusal ? (
        <p role="alert" className="border-t border-flag/60 bg-flag/20 px-3 py-2 text-sm">
          {gateRefusal}
        </p>
      ) : null}

      <footer className="flex flex-col gap-2 border-t border-slate-700 p-3 sm:flex-row">
        <button
          type="button"
          onClick={onConfirmAll}
          disabled={!allConfirmed || locked}
          title={
            allConfirmed
              ? "Renders the read-back from the confirmed fields and speaks it"
              : "Confirm every line first"
          }
          className={[
            "flex-1 rounded-lg border-4 px-4 py-4 text-lg font-extrabold uppercase tracking-wider transition-colors",
            allConfirmed && !locked
              ? "border-green-300 bg-confirm text-white hover:bg-green-700"
              : "cursor-not-allowed border-slate-700 bg-slate-800 text-slate-500",
          ].join(" ")}
        >
          {locked ? "✓ Confirmed & read back" : "Confirm & read back"}
        </button>
        <button
          type="button"
          onClick={onReject}
          disabled={locked || lines.length === 0}
          className="rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-40"
        >
          Discard draft
        </button>
      </footer>

      {!allConfirmed && lines.length > 0 ? (
        <p className="px-3 pb-3 text-xs text-slate-400">
          Nothing is spoken to the patient while any line is unconfirmed.
        </p>
      ) : null}
    </section>
  );
}

function RxLineRow({
  line,
  locked,
  touched,
  onTouch,
  onPatch,
  onConfirm,
}: {
  line: RxLine;
  locked: boolean;
  touched: Set<RequiredField>;
  onTouch: (field: RequiredField) => void;
  onPatch: (patch: Partial<RxLine>) => void;
  onConfirm: () => void;
}) {
  const [open, setOpen] = useState(false);
  const flagged = useMemo(() => fieldsNeedingTouch(line), [line]);
  const missing = useMemo(() => missingFields(line), [line]);
  const attention = needsAttention(line);
  const untouched = flagged.filter((f) => !touched.has(f));
  /** The low-confidence rule: the ✓ stays dead until every flagged field is touched. */
  const confirmBlocked = attention && untouched.length > 0;

  // Opening the editor is how the doctor touches a field, so a flagged line
  // starts open rather than hiding the problem behind a chevron.
  useEffect(() => {
    if (attention && !line.confirmed) setOpen(true);
  }, [attention, line.confirmed]);

  return (
    <li
      className={[
        "px-3 py-3",
        attention && !line.confirmed ? "border-l-4 border-amber-400 bg-amber-950/25" : "",
        line.confirmed ? "bg-green-950/20" : "",
      ].join(" ")}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        {/* drug_text is never normalised, corrected or expanded — docs/04 §2. */}
        <span className="text-lg font-bold">{line.drug_text || "— drug not captured"}</span>
        <span
          className={[
            "font-mono text-xl font-bold tabular-nums",
            line.strength_value === null
              ? "rounded bg-amber-900/50 px-1.5 text-amber-200"
              : "text-slate-50",
          ].join(" ")}
          title="Strength is never spoken in the read-back — this card is where it is checked"
        >
          {strengthDigits(line)}
        </span>
        <span className="rounded bg-slate-800 px-2 py-0.5 font-mono text-lg font-bold tabular-nums">
          {scheduleDigits(line.schedule)}
        </span>
        <span className="text-sm text-slate-300">{foodLabel(line.food_relation)}</span>
        <span className="font-mono text-sm tabular-nums text-slate-300">
          {durationDigits(line)}
        </span>
        {line.form ? <span className="text-xs text-slate-500">{line.form}</span> : null}
        <span className="ml-auto flex items-center gap-2">
          <span
            className={[
              "font-mono text-xs tabular-nums",
              isLowConfidence(line) ? "text-amber-300" : "text-slate-500",
            ].join(" ")}
            title={
              line.confidence === null
                ? "the console has not scored this line — treated as low confidence"
                : "extraction confidence"
            }
          >
            {confidenceDigits(line)}
          </span>
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            disabled={locked}
            aria-expanded={open}
            className="rounded border border-slate-600 px-2 py-1 text-sm hover:bg-slate-800 disabled:opacity-40"
          >
            ✎ Edit
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={locked || line.confirmed || confirmBlocked}
            title={
              confirmBlocked
                ? `Touch ${untouched.map((f) => FIELD_LABEL[f]).join(", ")} before confirming`
                : "Confirm this line"
            }
            className={[
              "rounded border-2 px-3 py-1 text-sm font-bold",
              line.confirmed
                ? "border-confirm bg-confirm/30 text-green-200"
                : confirmBlocked
                  ? "cursor-not-allowed border-slate-700 text-slate-500"
                  : "border-green-400 text-green-200 hover:bg-confirm/30",
            ].join(" ")}
          >
            {line.confirmed ? "✓ Confirmed" : "✓ Confirm"}
          </button>
        </span>
      </div>

      {line.notes ? (
        <p className="mt-1 text-sm text-slate-400">
          <span className="text-slate-500">notes: </span>
          {line.notes}
        </p>
      ) : null}

      {attention && !line.confirmed ? (
        <p className="mt-2 text-sm font-semibold text-amber-200">
          {isLowConfidence(line) ? "Low confidence — check the dose. " : null}
          {missing.length > 0
            ? `Not stated: ${missing.map((f) => FIELD_LABEL[f]).join(", ")}. `
            : null}
          {untouched.length > 0
            ? `Touch ${untouched.map((f) => FIELD_LABEL[f]).join(", ")} to enable ✓.`
            : "All flagged fields checked — ✓ is live."}
        </p>
      ) : null}

      {open && !locked ? (
        <LineEditor
          line={line}
          flagged={flagged}
          touched={touched}
          onTouch={onTouch}
          onPatch={onPatch}
        />
      ) : null}
    </li>
  );
}

function LineEditor({
  line,
  flagged,
  touched,
  onTouch,
  onPatch,
}: {
  line: RxLine;
  flagged: RequiredField[];
  touched: Set<RequiredField>;
  onTouch: (field: RequiredField) => void;
  onPatch: (patch: Partial<RxLine>) => void;
}) {
  const hl = (f: RequiredField) =>
    flagged.includes(f) && !touched.has(f)
      ? "ring-2 ring-amber-400"
      : "ring-1 ring-slate-700";

  /** Editing a field is a touch; so is explicitly keeping the value as heard. */
  const commit = (field: RequiredField, patch: Partial<RxLine>) => {
    onTouch(field);
    onPatch(patch);
  };

  return (
    <div className="mt-3 grid grid-cols-2 gap-3 rounded-lg bg-slate-950/60 p-3 sm:grid-cols-3">
      <Field label="Drug (as said)" flagField="drug_text" flagged={flagged} touched={touched}>
        <input
          className={`w-full rounded bg-slate-900 px-2 py-2 text-base ${hl("drug_text")}`}
          defaultValue={line.drug_text}
          onBlur={(e) => {
            onTouch("drug_text");
            if (e.target.value !== line.drug_text) onPatch({ drug_text: e.target.value });
          }}
        />
      </Field>

      <Field label="Strength" flagField="strength_value" flagged={flagged} touched={touched}>
        <input
          type="number"
          inputMode="numeric"
          min={0}
          max={5000}
          className={`w-full rounded bg-slate-900 px-2 py-2 font-mono text-lg tabular-nums ${hl("strength_value")}`}
          defaultValue={line.strength_value ?? ""}
          onBlur={(e) => {
            onTouch("strength_value");
            const v = e.target.value === "" ? null : Number(e.target.value);
            if (v !== line.strength_value) onPatch({ strength_value: v });
          }}
        />
      </Field>

      <Field label="Unit" flagField="strength_unit" flagged={flagged} touched={touched}>
        <select
          className={`w-full rounded bg-slate-900 px-2 py-2 text-base ${hl("strength_unit")}`}
          value={line.strength_unit ?? ""}
          // Blur counts as a touch: a sachet has no mg, and the doctor must be
          // able to look at the field and deliberately keep "— not stated".
          onBlur={() => onTouch("strength_unit")}
          onChange={(e) =>
            commit("strength_unit", {
              strength_unit: (e.target.value || null) as StrengthUnit,
            })
          }
        >
          {UNITS.map((u) => (
            <option key={String(u)} value={u ?? ""}>
              {u ?? "— not stated"}
            </option>
          ))}
        </select>
      </Field>

      <div className="col-span-2 sm:col-span-3">
        <span className="text-xs uppercase tracking-wider text-slate-400">
          Schedule (digits, morning-afternoon-night) — halves allowed
        </span>
        <div className="mt-1 flex items-center gap-2">
          {(["morning", "afternoon", "night"] as const).map((slot) => (
            <label key={slot} className="flex items-center gap-1">
              <span className="text-xs text-slate-400">{slot.slice(0, 3)}</span>
              <input
                type="number"
                inputMode="decimal"
                min={0}
                max={DOSE_MAX}
                // Half doses are legal and common; 0.25 is not. clampDose snaps
                // anything typed onto the nearest legal half.
                step={DOSE_STEP}
                className="w-20 rounded bg-slate-900 px-2 py-2 font-mono text-lg tabular-nums ring-1 ring-slate-700"
                value={line.schedule[slot]}
                onChange={(e) =>
                  onPatch({
                    schedule: {
                      ...line.schedule,
                      [slot]: clampDose(Number(e.target.value || 0)),
                    },
                  })
                }
              />
            </label>
          ))}
          <span className="ml-2 font-mono text-sm tabular-nums text-slate-400">
            = {totalPerDay(line.schedule)}/day
          </span>
        </div>
      </div>

      <Field label="Food" flagField="food_relation" flagged={flagged} touched={touched}>
        <select
          className={`w-full rounded bg-slate-900 px-2 py-2 text-base ${hl("food_relation")}`}
          value={line.food_relation ?? ""}
          onBlur={() => onTouch("food_relation")}
          onChange={(e) =>
            commit("food_relation", {
              food_relation: (e.target.value || null) as FoodRelation,
            })
          }
        >
          {FOODS.map((f) => (
            <option key={String(f)} value={f ?? ""}>
              {f ? foodLabel(f) : "— not stated"}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Days" flagField="duration_days" flagged={flagged} touched={touched}>
        <input
          type="number"
          inputMode="numeric"
          min={1}
          max={180}
          className={`w-full rounded bg-slate-900 px-2 py-2 font-mono text-lg tabular-nums ${hl("duration_days")}`}
          defaultValue={line.duration_days ?? ""}
          onBlur={(e) => {
            onTouch("duration_days");
            const v = e.target.value === "" ? null : Number(e.target.value);
            if (v !== line.duration_days) onPatch({ duration_days: v });
          }}
        />
      </Field>

      <Field label="Notes (read back verbatim)">
        <input
          className="w-full rounded bg-slate-900 px-2 py-2 text-base ring-1 ring-slate-700"
          defaultValue={line.notes ?? ""}
          onBlur={(e) => onPatch({ notes: e.target.value || null })}
        />
      </Field>
    </div>
  );
}

function Field({
  label,
  flagField,
  flagged,
  touched,
  children,
}: {
  label: string;
  flagField?: RequiredField;
  flagged?: RequiredField[];
  touched?: Set<RequiredField>;
  children: React.ReactNode;
}) {
  const needsTouch =
    flagField && flagged?.includes(flagField) && touched && !touched.has(flagField);
  return (
    <label className="block">
      <span className="text-xs uppercase tracking-wider text-slate-400">
        {label}
        {needsTouch ? <span className="ml-1 text-amber-300">• check</span> : null}
      </span>
      <span className="mt-1 block">{children}</span>
    </label>
  );
}
