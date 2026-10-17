/**
 * Prescription-line rules. Doses are rendered as digits everywhere on the
 * doctor's half — "fifteen" and "fifty" sound alike, the eye catches 15 vs 50
 * (docs/01 §2, §4).
 */

import type { FoodRelation, RxLine, Schedule } from "./types";

/** Below this, a line renders highlighted and cannot be confirmed with one tap. */
export const LOW_CONFIDENCE = 0.8;

/** Fields a line may not be confirmed without. `notes` and `form` are optional. */
export const REQUIRED_FIELDS = [
  "drug_text",
  "strength_value",
  "strength_unit",
  "food_relation",
  "duration_days",
] as const;

export type RequiredField = (typeof REQUIRED_FIELDS)[number];

/** Which required fields are missing on this line. */
export function missingFields(line: RxLine): RequiredField[] {
  const missing: RequiredField[] = [];
  if (!line.drug_text || line.drug_text.trim() === "") missing.push("drug_text");
  if (line.strength_value === null || line.strength_value === undefined)
    missing.push("strength_value");
  if (line.strength_unit === null || line.strength_unit === undefined)
    missing.push("strength_unit");
  if (line.food_relation === null || line.food_relation === undefined)
    missing.push("food_relation");
  if (line.duration_days === null || line.duration_days === undefined)
    missing.push("duration_days");
  return missing;
}

/**
 * A line is low-confidence if it scored below the threshold **or if it has no
 * score at all** — the console types `confidence` as `float | None` and leaves
 * it null until it has scored the line. An unscored line is not a confident
 * line, so it goes through the same touch-every-field gate. `null < 0.8` was
 * already true by JavaScript accident; this says it on purpose.
 */
export function isLowConfidence(line: RxLine): boolean {
  if (line.confidence === null || line.confidence === undefined) return true;
  return line.confidence < LOW_CONFIDENCE;
}

/**
 * The confidence chip's text. An unscored line reads as unscored — never 0.00,
 * which would claim the console scored it and found it worthless, and never
 * `.toFixed(2)` on a null, which throws and takes the doctor's whole half down
 * with it.
 */
export function confidenceDigits(line: RxLine): string {
  // Spelled out rather than imported from ./metrics-format so this module keeps
  // to `import type` only and loads in node's test runner with no build step.
  const c = line.confidence;
  return typeof c === "number" && Number.isFinite(c) ? c.toFixed(2) : "unscored";
}

/**
 * A line needing attention is highlighted and its per-line ✓ stays dead until the
 * doctor has touched every flagged field — either editing it or explicitly keeping
 * it. One careless tap must not clear a 50-vs-15 line.
 */
export function needsAttention(line: RxLine): boolean {
  return isLowConfidence(line) || missingFields(line).length > 0;
}

/** Every field the doctor must touch before this line can be confirmed. */
export function fieldsNeedingTouch(line: RxLine): RequiredField[] {
  const missing = missingFields(line);
  if (!isLowConfidence(line)) return missing;
  // A low-confidence line was mis-heard somewhere unknown, so the dose-bearing
  // fields all have to be looked at, not just the empty ones.
  const dose: RequiredField[] = ["drug_text", "strength_value", "duration_days"];
  return Array.from(new Set([...missing, ...dose]));
}

/** Dose values are multiples of 0.5 in 0–4 — docs/04 §2. */
export const DOSE_STEP = 0.5;
export const DOSE_MAX = 4;

/** Rejects 0.25 and 1.3 at the boundary; snaps to the nearest legal half. */
export function clampDose(value: number): number {
  if (!Number.isFinite(value)) return 0;
  const snapped = Math.round(value / DOSE_STEP) * DOSE_STEP;
  return Math.max(0, Math.min(DOSE_MAX, snapped));
}

export function isLegalDose(value: number): boolean {
  return (
    Number.isFinite(value) &&
    value >= 0 &&
    value <= DOSE_MAX &&
    Math.abs(value / DOSE_STEP - Math.round(value / DOSE_STEP)) < 1e-9
  );
}

/**
 * One dose as digits: `1`, `0.5`, `1.5`. Never a word — "half" and "one" are not
 * distinguishable at a glance the way `0.5` and `1` are, which is the same
 * reason doses are digits everywhere else on this screen.
 */
export function doseDigits(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

/** `1-0-1`, `1-0-0.5` — the form doctors read fastest, always digits. */
export function scheduleDigits(s: Schedule): string {
  return `${doseDigits(s.morning)}-${doseDigits(s.afternoon)}-${doseDigits(s.night)}`;
}

export function totalPerDay(s: Schedule): number {
  // Floating-point addition of halves, rounded back onto the legal grid.
  return clampDose(s.morning + s.afternoon + s.night);
}

/**
 * Splits a dose into whole units and a trailing half, for the picture card.
 * 1.5 → { whole: 1, half: true }.
 */
export function splitDose(value: number): { whole: number; half: boolean } {
  const legal = clampDose(value);
  return { whole: Math.floor(legal), half: legal % 1 !== 0 };
}

/**
 * Strength is deliberately NOT spoken in the read-back (docs/04 §2 rulings), so
 * the doctor's card and the picture card are the only places a strength figure
 * ever appears. It is the doctor's checkable artefact — render it, and render a
 * missing one loudly rather than as a quiet dash.
 */
export function strengthDigits(line: RxLine): string {
  if (line.strength_value === null) return "— strength not stated";
  return `${line.strength_value} ${line.strength_unit ?? ""}`.trim();
}

export const FOOD_LABEL: Record<Exclude<FoodRelation, null>, string> = {
  before_food: "before food",
  after_food: "after food",
  with_food: "with food",
};

export function foodLabel(f: FoodRelation): string {
  return f === null ? "— food timing not stated" : FOOD_LABEL[f];
}

export function durationDigits(line: RxLine): string {
  return line.duration_days === null ? "— days not stated" : `×${line.duration_days}d`;
}

export const FIELD_LABEL: Record<RequiredField, string> = {
  drug_text: "Drug",
  strength_value: "Strength",
  strength_unit: "Unit",
  food_relation: "Food",
  duration_days: "Days",
};
