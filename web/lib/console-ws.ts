/**
 * The console WebSocket: WS /ws/sessions/{id}, docs/04 §5.
 *
 * Every frame in §5 is consumed here and folded into one ConsoleView that the
 * components render. This file is the ONLY place that knows a socket exists, and
 * it behaves identically against `console --mock` and the real console — there is
 * no mock branch here or anywhere downstream.
 *
 * `state_snapshot` is always the first frame after connect, so a reconnect
 * re-reads the whole world for free; we just drop the view's volatile parts
 * (partials) and wait for it.
 */

import type { MetricValue } from "./metrics-format";
import type {
  ClientFrame,
  RedFlag,
  ServerFrame,
  SessionState,
  Side,
  StageTimings,
} from "./types";

/**
 * One `metric` frame, kept as it arrived. `reply_latency_ms` is nullable because
 * the console genuinely sends null (see `lib/types.ts`); we store the hole
 * rather than dropping the sample, so the HUD can say "4 turns, 2 measured"
 * instead of quietly pretending the other two never happened.
 */
export interface MetricSample {
  reply_latency_ms: number | null;
  stages: StageTimings;
  at: number;
}

export interface FailoverEvent {
  from: string;
  to: string;
  gap_ms: number | null;
}

export type ConnectionStatus = "idle" | "connecting" | "open" | "reconnecting" | "closed";

/** Everything the UI renders: the contract's SessionState plus frame-only extras. */
export interface ConsoleView {
  state: SessionState | null;
  /** Interim transcripts, keyed by side. Replaced by the next partial, cleared by a turn. */
  partials: Partial<Record<Side, string>>;
  /** From `rx_draft` — shown as a banner on the doctor's half. */
  ambiguities: string[];
  /** Latest `lang_detected`, for the language-confirm chip. */
  langDetected: { lang: string; confidence: number } | null;
  /** `metric` frames, newest last. */
  metrics: MetricSample[];
  /** `failover` frames — a demo beat, so we keep all of them. */
  failovers: FailoverEvent[];
  /** The exact string `readback_started` carried, for the doctor to eyeball. */
  readback: { text: string; language: string } | null;
  errors: { code: string; message: string }[];
  endedReason: string | null;
  connection: ConnectionStatus;
}

export const emptyView: ConsoleView = {
  state: null,
  partials: {},
  ambiguities: [],
  langDetected: null,
  metrics: [],
  failovers: [],
  readback: null,
  errors: [],
  endedReason: null,
  connection: "idle",
};

/** Pure fold of one server frame into the view. Exported so it is testable. */
export function reduceFrame(view: ConsoleView, frame: ServerFrame): ConsoleView {
  switch (frame.type) {
    case "state_snapshot":
      // Authoritative. Keeps frame-only extras that the snapshot does not carry.
      return { ...view, state: frame.state, partials: {} };

    case "stage":
      if (!view.state) return view;
      return { ...view, state: { ...view.state, stage: frame.stage } };

    case "turn": {
      if (!view.state) return view;
      const turns = view.state.turns.some((t) => t.id === frame.turn.id)
        ? view.state.turns.map((t) => (t.id === frame.turn.id ? frame.turn : t))
        : [...view.state.turns, frame.turn];
      const partials = { ...view.partials };
      delete partials[frame.turn.side];
      return { ...view, state: { ...view.state, turns }, partials };
    }

    case "partial":
      return { ...view, partials: { ...view.partials, [frame.side]: frame.text } };

    case "lang_detected": {
      const langDetected = { lang: frame.lang, confidence: frame.confidence };
      if (!view.state) return { ...view, langDetected };
      return {
        ...view,
        langDetected,
        state: {
          ...view.state,
          patient_language: frame.lang as SessionState["patient_language"],
        },
      };
    }

    case "red_flag": {
      if (!view.state) return view;
      const red_flags: RedFlag[] = view.state.red_flags.some((f) => f.id === frame.red_flag.id)
        ? view.state.red_flags.map((f) => (f.id === frame.red_flag.id ? frame.red_flag : f))
        : [...view.state.red_flags, frame.red_flag];
      return { ...view, state: { ...view.state, red_flags } };
    }

    case "rx_draft": {
      if (!view.state) return view;
      return {
        ...view,
        ambiguities: frame.ambiguities ?? [],
        state: {
          ...view.state,
          prescription: {
            lines: frame.lines,
            all_confirmed: frame.lines.length > 0 && frame.lines.every((l) => l.confirmed),
            confirmed_at: null,
          },
        },
      };
    }

    case "rx_line_updated": {
      if (!view.state) return view;
      const lines = view.state.prescription.lines.map((l) =>
        l.id === frame.line.id ? frame.line : l,
      );
      return {
        ...view,
        state: {
          ...view.state,
          prescription: {
            ...view.state.prescription,
            lines,
            all_confirmed: lines.length > 0 && lines.every((l) => l.confirmed),
          },
        },
      };
    }

    case "rx_locked": {
      if (!view.state) return view;
      return {
        ...view,
        state: {
          ...view.state,
          prescription: {
            ...view.state.prescription,
            all_confirmed: true,
            confirmed_at: frame.confirmed_at,
          },
        },
      };
    }

    case "readback_started":
      return { ...view, readback: { text: frame.text, language: frame.language } };

    case "teachback_result":
      if (!view.state) return view;
      return { ...view, state: { ...view.state, teachback: frame.result } };

    case "voice_note": {
      const voice_note = { token: frame.token, qr_data_uri: frame.qr_data_uri };
      if (!view.state) return view;
      return { ...view, state: { ...view.state, voice_note } };
    }

    case "metric": {
      const metrics = [
        ...view.metrics,
        { reply_latency_ms: frame.reply_latency_ms, stages: frame.stages, at: Date.now() },
      ].slice(-40);
      const state = view.state
        ? {
            ...view.state,
            metrics: {
              ...view.state.metrics,
              turns: view.state.metrics.turns,
              last_reply_latency_ms: frame.reply_latency_ms,
              reply_latency_p90_ms: p90(metrics.map((m) => m.reply_latency_ms)),
            },
          }
        : view.state;
      return { ...view, metrics, state };
    }

    case "failover":
      return {
        ...view,
        failovers: [...view.failovers, { from: frame.from, to: frame.to, gap_ms: frame.gap_ms }],
      };

    case "error":
      return {
        ...view,
        errors: [...view.errors, { code: frame.code, message: frame.message }].slice(-6),
      };

    case "session_ended": {
      const state = view.state ? { ...view.state, stage: "ended" as const } : view.state;
      return { ...view, state, endedReason: frame.reason };
    }

    default:
      // Unknown frame types are ignored rather than thrown: the console may ship
      // a new frame before the UI knows about it.
      return view;
  }
}

/**
 * p90 over the measured values only. Holes are dropped, not counted as zero: a
 * single unmeasured turn read as 0 ms would drag a p90 down and turn a slow call
 * green. Returns null when nothing was measured — there is no p90 of nothing.
 */
export function p90(values: readonly MetricValue[]): number | null {
  // Inlined rather than imported from ./metrics-format on purpose: every other
  // import in this file is `import type`, so the module erases to plain JS and
  // node's own test runner can load it with no build step and no new dependency.
  const measured = values.filter(
    (v): v is number => typeof v === "number" && Number.isFinite(v),
  );
  if (measured.length === 0) return null;
  const sorted = [...measured].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.ceil(sorted.length * 0.9) - 1);
  return sorted[Math.max(0, idx)];
}

function isServerFrame(value: unknown): value is ServerFrame {
  return typeof value === "object" && value !== null && typeof (value as { type?: unknown }).type === "string";
}

export interface ConsoleSocketOptions {
  /** Base console URL, e.g. http://127.0.0.1:8808 */
  consoleUrl: string;
  sessionId: string;
  onView: (view: ConsoleView) => void;
  /** Called for every frame, for side effects such as barge-in or audio. */
  onFrame?: (frame: ServerFrame) => void;
}

/**
 * Owns one socket for one session. Reconnects with backoff; each reconnect gets a
 * fresh `state_snapshot` from the server, which is how we recover state.
 */
export class ConsoleSocket {
  private ws: WebSocket | null = null;
  private view: ConsoleView;
  private closedByUs = false;
  private attempt = 0;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;

  // Written out rather than declared as a constructor parameter property: a
  // parameter property is TypeScript that cannot be *erased*, only compiled, so
  // node's strip-only TypeScript refuses the file and `npm test` cannot import
  // this module at all. Nothing else changes.
  private readonly opts: ConsoleSocketOptions;

  constructor(opts: ConsoleSocketOptions) {
    this.opts = opts;
    this.view = { ...emptyView };
  }

  connect(): void {
    this.closedByUs = false;
    this.open();
  }

  private open(): void {
    const url = wsUrl(this.opts.consoleUrl, this.opts.sessionId);
    this.publish({ connection: this.attempt === 0 ? "connecting" : "reconnecting" });

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      this.scheduleRetry();
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      this.attempt = 0;
      this.publish({ connection: "open" });
      this.pingTimer = setInterval(() => this.send({ type: "ping" }), 15_000);
    };

    ws.onmessage = (ev: MessageEvent) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(typeof ev.data === "string" ? ev.data : "");
      } catch {
        return;
      }
      if (!isServerFrame(parsed)) return;
      this.view = reduceFrame(this.view, parsed);
      this.opts.onView(this.view);
      this.opts.onFrame?.(parsed);
    };

    ws.onerror = () => {
      /* onclose always follows; retry is handled there. */
    };

    ws.onclose = () => {
      if (this.pingTimer) {
        clearInterval(this.pingTimer);
        this.pingTimer = null;
      }
      if (this.closedByUs) {
        this.publish({ connection: "closed" });
        return;
      }
      // Drop volatile parts; the next snapshot is authoritative.
      this.view = { ...this.view, partials: {} };
      this.scheduleRetry();
    };
  }

  private scheduleRetry(): void {
    this.attempt += 1;
    const delay = Math.min(8_000, 400 * 2 ** (this.attempt - 1));
    this.publish({ connection: "reconnecting" });
    this.retryTimer = setTimeout(() => this.open(), delay);
  }

  /** Advisory `ptt` / `ping` frames. Push-to-talk itself is a LiveKit track mute. */
  send(frame: ClientFrame): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(frame));
    }
  }

  close(): void {
    this.closedByUs = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.ws?.close();
  }

  private publish(patch: Partial<ConsoleView>): void {
    this.view = { ...this.view, ...patch };
    this.opts.onView(this.view);
  }
}

export function wsUrl(consoleUrl: string, sessionId: string): string {
  const base = consoleUrl.replace(/^http/, "ws").replace(/\/$/, "");
  return `${base}/ws/sessions/${sessionId}`;
}
