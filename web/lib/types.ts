/**
 * Shapes from docs/04-interfaces.md §2 and §5. That file is the law: field names
 * are exact and nothing is renamed at this edge.
 */

export type Side = "patient" | "doctor" | "agent";

export type PatientLanguage = "ta" | "kn" | "hi" | "unsupported" | "";

export type Stage =
  | "start"
  | "consent"
  | "interpret"
  | "prescribe"
  | "await_confirm"
  | "readback"
  | "teachback"
  | "takehome"
  | "ended";

/**
 * Multiples of 0.5 from 0 to 4 inclusive — docs/04 §2 (changed from int on
 * 2026-10-17). `1`, `0.5` and `1.5` are legal; `0.25` and `1.3` are not and are
 * rejected at the type boundary by `clampDose` in lib/rx.ts.
 *
 * "Half a tablet twice a day" is one of the commonest dosing forms in Indian
 * practice, so this is a real value, not an edge case.
 */
export interface Schedule {
  morning: number;
  afternoon: number;
  night: number;
}

export type StrengthUnit = "mg" | "ml" | "g" | "iu" | "drops" | null;
export type RxForm =
  | "tablet"
  | "capsule"
  | "syrup"
  | "injection"
  | "drops"
  | "ointment"
  | null;
export type FoodRelation = "before_food" | "after_food" | "with_food" | null;

export interface RxLine {
  id: string;
  drug_text: string;
  strength_value: number | null;
  strength_unit: StrengthUnit;
  form: RxForm;
  schedule: Schedule;
  food_relation: FoodRelation;
  duration_days: number | null;
  notes: string | null;
  /**
   * `float | None` on both sides of the wire — `console/app/models.py:RxLine` and
   * `vaidyavaani-agent/state.py:RxLine` both default it to `None`, because the
   * console scores confidence and may not have scored this line yet. Typed
   * `number` here it was a crash, not a cosmetic bug: `line.confidence.toFixed(2)`
   * throws on null and takes the whole doctor's half down with it.
   */
  confidence: number | null;
  confirmed: boolean;
}

export interface LayTerm {
  said: string;
  likely_means: string;
}

export interface Turn {
  id: string;
  side: Side;
  original_text: string;
  english_text: string;
  detected_language: string;
  lay_terms: LayTerm[];
  negations: string[];
  at: string;
}

export interface RedFlag {
  id: string;
  phrase: string;
  english: string;
  source: "keyword" | "llm";
  severity: "watch" | "urgent";
  at: string;
  acknowledged: boolean;
}

export type TeachBackVerdict = "match" | "mismatch" | "not_mentioned";

export interface TeachBackLine {
  line_id: string;
  morning: TeachBackVerdict;
  afternoon: TeachBackVerdict;
  night: TeachBackVerdict;
  duration: TeachBackVerdict;
  food_relation: TeachBackVerdict;
  patient_said: Record<string, unknown>;
}

export interface TeachBackResult {
  overall: "match" | "mismatch" | "not_mentioned";
  per_line: TeachBackLine[];
  mismatched_fields: string[];
  simplest_restatement: string;
}

export interface Prescription {
  lines: RxLine[];
  all_confirmed: boolean;
  confirmed_at: string | null;
}

export interface VoiceNote {
  token: string;
  qr_data_uri: string;
}

export interface Metrics {
  turns: number;
  reply_latency_p90_ms: number | null;
  last_reply_latency_ms: number | null;
}

export interface SessionState {
  session_id: string;
  patient_language: PatientLanguage;
  doctor_language: string;
  consent: { given: boolean; at: string | null } | null;
  stage: Stage;
  turns: Turn[];
  red_flags: RedFlag[];
  prescription: Prescription;
  teachback: TeachBackResult | null;
  voice_note: VoiceNote | null;
  metrics: Metrics;
}

/** POST /api/sessions response — docs/04 §4. */
export interface SessionCreated {
  session_id: string;
  livekit_url: string;
  livekit_token: string;
  room_name: string;
}

/**
 * Per-stage timings from the `metric` frame. Every stage is optional *and*
 * nullable: `console/app/metrics.py:latest_frame` omits a stage it has no value
 * for, and a `state: "unavailable"` record in unmute's dev.log carries no
 * `value` key at all (docs/00-HANDOVER §12). An absent stage is an absent
 * measurement — never a zero. See `lib/metrics-format.ts`.
 */
export interface StageTimings {
  stt?: number | null;
  llm_ttft?: number | null;
  tts_first_audio?: number | null;
}

/* ── Server → browser frames, docs/04 §5 ───────────────────────────────── */

export type ServerFrame =
  | { type: "state_snapshot"; state: SessionState }
  | { type: "stage"; stage: Stage }
  | { type: "turn"; turn: Turn }
  | { type: "partial"; side: Side; text: string }
  | { type: "lang_detected"; lang: string; confidence: number }
  | { type: "red_flag"; red_flag: RedFlag }
  | { type: "rx_draft"; lines: RxLine[]; ambiguities: string[] }
  | { type: "rx_line_updated"; line: RxLine }
  | { type: "rx_locked"; confirmed_at: string }
  | { type: "readback_started"; text: string; language: string }
  | { type: "teachback_result"; result: TeachBackResult }
  | { type: "voice_note"; token: string; qr_data_uri: string }
  | {
      type: "metric";
      /**
       * Nullable on the wire: `console/app/metrics.py:latest_frame` returns
       * `{"type": "metric", "reply_latency_ms": None, "stages": {}}` when the dev
       * log holds no record it recognises. Typed `number`, that null reached
       * `bandFor`, where `null <= 900` is **true**, and painted an unmeasured
       * turn green.
       */
      reply_latency_ms: number | null;
      stages: StageTimings;
    }
  | { type: "failover"; from: string; to: string; gap_ms: number | null }
  | { type: "error"; code: string; message: string }
  | { type: "session_ended"; reason: string };

/* ── Browser → server frames, docs/04 §5 ───────────────────────────────── */

export type ClientFrame =
  | { type: "ptt"; side: "patient" | "doctor"; state: "down" | "up" }
  | { type: "ping" };
