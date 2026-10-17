#!/usr/bin/env node
/**
 * ─────────────────────────────────────────────────────────────────────────────
 *  DEV-ONLY STUB.  Not the console.  Not shipped.  Not a source of truth.
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * A ~single-file stand-in for `console --mock`, implementing just enough of
 * docs/04 §3–§5 for `web/` to be built and demoed with nothing else running.
 * The real console (owned by the `console-backend` session) replaces it wholesale;
 * `web/lib/console-ws.ts` cannot tell the difference, which is the point.
 *
 * What it is NOT:
 *   · It mints a fake LiveKit token. Audio will not connect against this stub —
 *     the UI stays usable and says "no audio". Run the real console for audio.
 *   · Its QR is a drawn placeholder, not a scannable code. The real console mints
 *     a real one from a tokenised URL.
 *   · It does no dose arithmetic and renders no read-back template. It echoes a
 *     canned Tamil string so the screen has something to show.
 *
 * The consultation is DRIVEN BY THE UI: each push-to-talk release advances the
 * canned Tamil script, so the six-step flow in docs/01 §3 is clickable.
 *
 *   node mocks/console-mock.mjs            # :8808
 *   PORT=9999 node mocks/console-mock.mjs
 *
 * Zero dependencies: stdlib http + a hand-rolled RFC 6455 server, so this stub
 * never adds anything to package.json.
 */

import http from "node:http";
import crypto from "node:crypto";

const PORT = Number(process.env.PORT ?? 8808);
const HOST = "127.0.0.1";

/* ── session store ──────────────────────────────────────────────────────── */

/** @type {Map<string, {state: any, sockets: Set<any>, beat: number, ambiguities: string[]}>} */
const sessions = new Map();

function newState(id) {
  return {
    session_id: id,
    patient_language: "",
    doctor_language: "en",
    consent: null,
    stage: "start",
    turns: [],
    red_flags: [],
    prescription: { lines: [], all_confirmed: false, confirmed_at: null },
    teachback: null,
    voice_note: null,
    metrics: { turns: 0, reply_latency_p90_ms: null, last_reply_latency_ms: null },
  };
}

function send(session, frame) {
  for (const ws of session.sockets) wsSend(ws, JSON.stringify(frame));
}

function nowIso() {
  return new Date().toISOString().replace(/\.\d+Z$/, "Z");
}

/* ── the canned Tamil consultation (docs/01 §8, the 0:20–1:20 beat) ─────── */

let turnSeq = 0;
const nextTurnId = () => `t_${++turnSeq}`;

/**
 * How much of a `metric` frame this run pretends to have measured.
 *
 *   METRICS_MODE=full      every turn fully timed (the default, and the demo)
 *   METRICS_MODE=partial   the shape a half-working dev.log really produces:
 *                          some turns with no latency at all, and the STT stage
 *                          permanently missing
 *   METRICS_MODE=none      no `metric` frame ever sent
 *
 * `partial` is not invented. docs/00-HANDOVER §6 and §12: a `state:
 * "unavailable"` record in unmute's dev.log has **no `value` key**, and
 * `console/app/metrics.py:latest_frame` answers that with
 * `{"type": "metric", "reply_latency_ms": null, "stages": {}}`. The STT stage in
 * particular may never populate at all, because the only STT measurement unmute
 * emits is `request_duration`, which is `None` for a streaming STT and Saaras
 * streams. These three modes are how the HUD's "unmeasured" paths get looked at
 * with eyes instead of assumed.
 */
const METRICS_MODE = process.env.METRICS_MODE ?? "full";

let metricSeq = 0;

function metric(session, ms, stages) {
  if (METRICS_MODE === "none") return;

  metricSeq += 1;
  let frameMs = ms;
  let frameStages = stages;

  if (METRICS_MODE === "partial") {
    // Every third turn arrives with no timing at all; STT is never there.
    const { stt: _dropped, ...rest } = stages;
    frameStages = metricSeq % 2 === 0 ? { ...rest, tts_first_audio: null } : rest;
    if (metricSeq % 3 === 0) {
      frameMs = null;
      frameStages = {};
    }
  }

  session.state.metrics.turns += 1;
  session.state.metrics.last_reply_latency_ms = frameMs;
  send(session, { type: "metric", reply_latency_ms: frameMs, stages: frameStages });
}

function pushTurn(session, turn) {
  const full = { id: nextTurnId(), lay_terms: [], negations: [], at: nowIso(), ...turn };
  session.state.turns.push(full);
  send(session, { type: "turn", turn: full });
  return full;
}

function setStage(session, stage) {
  session.state.stage = stage;
  send(session, { type: "stage", stage });
}

/** Trickle a partial out character-group by character-group, then the full turn. */
function streamPartial(session, side, text, thenMs, then) {
  const chunks = Math.max(2, Math.min(5, Math.ceil(text.length / 12)));
  for (let i = 1; i <= chunks; i++) {
    setTimeout(
      () =>
        send(session, {
          type: "partial",
          side,
          text: text.slice(0, Math.ceil((text.length * i) / chunks)) + (i < chunks ? "…" : ""),
        }),
      i * 160,
    );
  }
  setTimeout(then, chunks * 160 + thenMs);
}

/**
 * Beats, in order, each triggered by a push-to-talk release from the side named.
 * `any` accepts either side, so a demo that presses the wrong button still moves.
 */
const BEATS = [
  {
    side: "patient",
    run(session) {
      // Step 1: language detect, then spoken confirmation, then consent.
      send(session, { type: "lang_detected", lang: "ta", confidence: 0.93 });
      session.state.patient_language = "ta";
      streamPartial(session, "patient", "வணக்கம்", 120, () => {
        pushTurn(session, {
          side: "patient",
          original_text: "வணக்கம், எனக்கு உடம்பு சரியில்லை",
          english_text: "Hello, I am not well",
          detected_language: "ta",
        });
        metric(session, 780, { stt: 300, llm_ttft: 250, tts_first_audio: 230 });
        setStage(session, "consent");
        setTimeout(() => {
          session.state.consent = { given: true, at: nowIso() };
          send(session, { type: "state_snapshot", state: session.state });
          setStage(session, "interpret");
        }, 700);
      });
    },
  },
  {
    side: "patient",
    run(session) {
      // Step 2: the presenting complaint.
      streamPartial(session, "patient", "காய்ச்சல் மூன்று நாள்", 150, () => {
        pushTurn(session, {
          side: "patient",
          original_text: "காய்ச்சல் மூன்று நாள், சிறுநீர் கழிக்கும்போது எரிச்சல்",
          english_text: "Fever for three days, burning when passing urine",
          detected_language: "ta",
          lay_terms: [{ said: "உடல் சூடு", likely_means: "fever / body heat" }],
        });
        metric(session, 840, { stt: 310, llm_ttft: 260, tts_first_audio: 210 });
      });
    },
  },
  {
    side: "doctor",
    run(session) {
      // The doctor speaks English, so their turn IS English on both fields; the
      // Tamil the patient hears arrives as the agent's interpretation turn.
      pushTurn(session, {
        side: "doctor",
        original_text: "Any shivering with the fever? Any back pain?",
        english_text: "Any shivering with the fever? Any back pain?",
        detected_language: "en",
      });
      setTimeout(
        () =>
          pushTurn(session, {
            side: "agent",
            original_text: "காய்ச்சலுடன் நடுக்கம் இருக்கிறதா? முதுகுவலி உள்ளதா?",
            english_text: "Any shivering with the fever? Any back pain?",
            detected_language: "ta",
          }),
        500,
      );
      metric(session, 910, { stt: 290, llm_ttft: 380, tts_first_audio: 240 });
    },
  },
  {
    side: "patient",
    run(session) {
      // Step 3: red flag lands mid-sentence, on the doctor's half only.
      setTimeout(
        () =>
          send(session, {
            type: "red_flag",
            red_flag: {
              id: "rf_1",
              phrase: "நடுக்கம்",
              english: "shivering with fever",
              source: "keyword",
              severity: "watch",
              at: nowIso(),
              acknowledged: false,
            },
          }),
        220,
      );
      streamPartial(session, "patient", "ஆம், நடுக்கம் இருக்கிறது", 150, () => {
        pushTurn(session, {
          side: "patient",
          original_text: "ஆம், நடுக்கம் இருக்கிறது, முதுகுவலியும் இருக்கிறது",
          english_text: "Yes, there is shivering, and back pain as well",
          detected_language: "ta",
          negations: ["no chest pain"],
        });
        // The confirming layer upgrades the keyword flag.
        send(session, {
          type: "red_flag",
          red_flag: {
            id: "rf_1",
            phrase: "நடுக்கம், முதுகுவலி",
            english: "shivering + flank/back pain with fever — possible pyelonephritis",
            source: "llm",
            severity: "urgent",
            at: nowIso(),
            acknowledged: false,
          },
        });
        metric(session, 1180, { stt: 420, llm_ttft: 480, tts_first_audio: 280 });
      });
    },
  },
  {
    side: "doctor",
    run(session) {
      // Step 4: the draft. Line 2 carries the demo's safety moment: the doctor
      // said "fifty", extraction heard it at 0.58 confidence, and line 3 has a
      // null strength. Neither is confirmable with one tap.
      setStage(session, "prescribe");
      const lines = [
        {
          id: "rx_1",
          drug_text: "Paracetamol",
          strength_value: 500,
          strength_unit: "mg",
          form: "tablet",
          schedule: { morning: 1, afternoon: 0, night: 1 },
          food_relation: "after_food",
          duration_days: 5,
          notes: null,
          confidence: 0.94,
          confirmed: false,
        },
        {
          id: "rx_2",
          drug_text: "Nitrofurantoin",
          strength_value: 50,
          strength_unit: "mg",
          form: "tablet",
          schedule: { morning: 1, afternoon: 0, night: 1 },
          food_relation: "after_food",
          duration_days: 5,
          notes: null,
          confidence: 0.58,
          confirmed: false,
        },
        {
          id: "rx_3",
          drug_text: "ORS",
          strength_value: null,
          strength_unit: null,
          form: "syrup",
          schedule: { morning: 1, afternoon: 1, night: 1 },
          food_relation: null,
          duration_days: 3,
          notes: "one sachet in one litre of water",
          // Deliberately unscored. `confidence` is `float | None` in both
          // console/app/models.py and vaidyavaani-agent/state.py, so a line the
          // console has not scored yet is a real thing the UI must survive.
          // Rendered as `0.00` it would read as "the console scored this and
          // found it worthless"; run through `.toFixed(2)` it threw and took the
          // whole doctor's half down. It renders "unscored" and is treated as
          // low confidence.
          confidence: null,
          confirmed: false,
        },
        {
          // Half doses, docs/04 §2: "half a tablet in the morning, half at
          // night". Low confidence on purpose — this is the line the model is
          // least sure about, so it must also be unconfirmable in one tap.
          id: "rx_4",
          drug_text: "Amlodipine",
          strength_value: 5,
          strength_unit: "mg",
          form: "tablet",
          schedule: { morning: 0.5, afternoon: 0, night: 0.5 },
          food_relation: "after_food",
          duration_days: 30,
          notes: null,
          confidence: 0.71,
          confirmed: false,
        },
      ];
      session.state.prescription = { lines, all_confirmed: false, confirmed_at: null };
      session.ambiguities = [
        "strength of 2nd drug heard as 50 mg at low confidence — doctor may have said 100",
        "food timing of 3rd line not stated",
        "4th drug heard as half a tablet — confirm it is 0.5 and not 1",
      ];
      send(session, { type: "rx_draft", lines, ambiguities: session.ambiguities });
      setStage(session, "await_confirm");
      metric(session, 1240, { stt: 460, llm_ttft: 520, tts_first_audio: 260 });
      // F11, the live failover beat.
      setTimeout(
        () => send(session, { type: "failover", from: "indic", to: "multi_backup", gap_ms: 1240 }),
        900,
      );
    },
  },
  {
    side: "any",
    run(session) {
      pushTurn(session, {
        side: "doctor",
        original_text: "Drink plenty of water. Come back if the fever does not settle.",
        english_text: "Drink plenty of water. Come back if the fever does not settle.",
        detected_language: "en",
      });
      setTimeout(
        () =>
          pushTurn(session, {
            side: "agent",
            original_text: "நிறைய தண்ணீர் குடிக்கவும். காய்ச்சல் குறையவில்லை என்றால் திரும்ப வாருங்கள்.",
            english_text: "Drink plenty of water. Come back if the fever does not settle.",
            detected_language: "ta",
          }),
        500,
      );
      metric(session, 870, { stt: 300, llm_ttft: 320, tts_first_audio: 250 });
    },
  },
];

function advance(session, side) {
  const beat = BEATS[session.beat];
  if (!beat) return;
  if (beat.side !== "any" && beat.side !== side) return;
  session.beat += 1;
  beat.run(session);
}

/** Steps 5 and 6, triggered by the doctor's confirm-all tap. */
function runReadbackAndTakehome(session) {
  session.state.prescription.all_confirmed = true;
  session.state.prescription.confirmed_at = nowIso();
  send(session, { type: "rx_locked", confirmed_at: session.state.prescription.confirmed_at });
  setStage(session, "readback");

  const readback =
    "காலையில் சாப்பிட்ட பிறகு ஒரு மாத்திரை, இரவில் ஒரு மாத்திரை, ஐந்து நாட்களுக்கு.";
  setTimeout(
    () => send(session, { type: "readback_started", text: readback, language: "ta" }),
    400,
  );

  setTimeout(() => {
    setStage(session, "teachback");
    const result = {
      // `TEACHBACK_OVERALL=not_mentioned` replays the third verdict, the one a
      // two-way red/green panel used to paint as a pass. `match | mismatch |
      // not_mentioned` per docs/04 §2; the demo default stays `mismatch`,
      // because catching a misunderstanding is the beat worth showing.
      overall: process.env.TEACHBACK_OVERALL ?? "mismatch",
      per_line: [
        {
          line_id: "rx_1",
          morning: "match",
          afternoon: "not_mentioned",
          night: "match",
          duration: "mismatch",
          food_relation: "match",
          patient_said: { duration_days: 2 },
        },
      ],
      mismatched_fields: ["rx_1.duration"],
      simplest_restatement: "Five days, not two days.",
    };
    session.state.teachback = result;
    send(session, { type: "teachback_result", result });
  }, 2200);

  setTimeout(() => {
    setStage(session, "takehome");
    send(session, {
      type: "voice_note",
      token: "vn_mock9",
      qr_data_uri: placeholderQr(),
    });
  }, 3800);
}

/**
 * A drawn QR-shaped placeholder, so the layout is honest at scanning size.
 * It is NOT a scannable code — the real console mints one from a tokenised URL.
 */
function placeholderQr() {
  const n = 25;
  const cells = [];
  const finder = (ox, oy) => {
    for (let y = 0; y < 7; y++)
      for (let x = 0; x < 7; x++) {
        const edge = x === 0 || y === 0 || x === 6 || y === 6;
        const core = x >= 2 && x <= 4 && y >= 2 && y <= 4;
        if (edge || core) cells.push([ox + x, oy + y]);
      }
  };
  finder(0, 0);
  finder(n - 7, 0);
  finder(0, n - 7);
  // Deterministic pseudo-data so the image does not flicker between renders.
  for (let y = 0; y < n; y++)
    for (let x = 0; x < n; x++) {
      const inFinder =
        (x < 8 && y < 8) || (x > n - 9 && y < 8) || (x < 8 && y > n - 9);
      if (inFinder) continue;
      if ((x * 7 + y * 13 + ((x * y) % 5)) % 3 === 0) cells.push([x, y]);
    }
  const rects = cells.map(([x, y]) => `<rect x="${x}" y="${y}" width="1" height="1"/>`).join("");
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="-1 -1 ${n + 2} ${n + 4}" shape-rendering="crispEdges">` +
    `<rect x="-1" y="-1" width="${n + 2}" height="${n + 4}" fill="#fff"/>` +
    `<g fill="#000">${rects}</g>` +
    `<text x="${n / 2}" y="${n + 2.4}" font-size="1.6" text-anchor="middle" fill="#777" font-family="sans-serif">DEV STUB — not scannable</text>` +
    `</svg>`;
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}`;
}

/* ── HTTP, docs/04 §4 (browser-facing) and §3 (agent-facing) ───────────── */

function json(res, code, body) {
  const text = JSON.stringify(body);
  res.writeHead(code, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(text),
    // Next.js dev is a different origin from the console; the real console does
    // the same for 127.0.0.1.
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type, X-Console-Token",
    "Access-Control-Allow-Methods": "GET, POST, PATCH, OPTIONS",
  });
  res.end(text);
}

async function readBody(req) {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  if (chunks.length === 0) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
  } catch {
    return {};
  }
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", `http://${HOST}:${PORT}`);
  const path = url.pathname;
  const method = req.method ?? "GET";

  if (method === "OPTIONS") return json(res, 204, {});
  if (path === "/healthz") {
    return json(res, 200, { ok: true, livekit: false, console_version: "mock-stub" });
  }

  if (path === "/api/sessions" && method === "POST") {
    const id = `s_${crypto.randomBytes(3).toString("hex")}`;
    sessions.set(id, { state: newState(id), sockets: new Set(), beat: 0, ambiguities: [] });
    console.log(`[mock] session ${id}`);
    return json(res, 200, {
      session_id: id,
      // Deliberately unusable: this stub does not run LiveKit. The UI degrades to
      // "no audio" and everything visual still works.
      livekit_url: "ws://127.0.0.1:7880",
      livekit_token: "mock-token-no-livekit",
      room_name: `vv-${id}`,
    });
  }

  const m = /^\/api\/sessions\/([^/]+)(\/.*)?$/.exec(path);
  if (m) {
    const session = sessions.get(m[1]);
    if (!session) return json(res, 404, { error: "no such session" });
    const rest = m[2] ?? "";
    const body = method === "GET" ? {} : await readBody(req);

    if (rest === "" && method === "GET") return json(res, 200, session.state);

    if (rest === "/language" && method === "POST") {
      if (body.side === "doctor") session.state.doctor_language = body.lang;
      else session.state.patient_language = body.lang;
      send(session, { type: "state_snapshot", state: session.state });
      return json(res, 200, { ok: true });
    }

    if (rest === "/consent" && method === "POST") {
      session.state.consent = { given: !!body.given, at: nowIso() };
      send(session, { type: "state_snapshot", state: session.state });
      return json(res, 200, { ok: true });
    }

    if (rest === "/metrics" && method === "GET") {
      return json(res, 200, session.state.metrics);
    }

    if (rest === "/end" && method === "POST") {
      send(session, { type: "session_ended", reason: "doctor ended" });
      sessions.delete(m[1]);
      return json(res, 200, { ok: true });
    }

    const rx = /^\/rx(?:\/([^/]+))?(?:\/(confirm|confirm-all|reject))?$/.exec(rest);
    if (rx) {
      const lineId = rx[1];
      const action = rx[2] ?? (lineId === "confirm-all" ? "confirm-all" : lineId === "reject" ? "reject" : undefined);
      const lines = session.state.prescription.lines;

      if (action === "confirm-all") {
        // The real gate, docs/04 §4: 409 while any line is unconfirmed.
        if (lines.length === 0 || lines.some((l) => !l.confirmed)) {
          return json(res, 409, { error: "unconfirmed lines remain" });
        }
        runReadbackAndTakehome(session);
        return json(res, 200, { ok: true });
      }

      if (action === "reject") {
        session.state.prescription = { lines: [], all_confirmed: false, confirmed_at: null };
        session.ambiguities = [];
        send(session, { type: "rx_draft", lines: [], ambiguities: [] });
        setStage(session, "interpret");
        return json(res, 200, { ok: true });
      }

      const line = lines.find((l) => l.id === lineId);
      if (!line) return json(res, 404, { error: "no such line" });

      if (action === "confirm" && method === "POST") {
        line.confirmed = true;
        session.state.prescription.all_confirmed = lines.every((l) => l.confirmed);
        send(session, { type: "rx_line_updated", line });
        return json(res, 200, { ok: true });
      }

      if (method === "PATCH") {
        // An edit clears `confirmed` — docs/04 §4.
        for (const [k, v] of Object.entries(body)) {
          if (k === "id" || k === "confirmed") continue;
          line[k] = v;
        }
        line.confirmed = false;
        session.state.prescription.all_confirmed = false;
        send(session, { type: "rx_line_updated", line });
        return json(res, 200, { line });
      }
    }
  }

  if (path.startsWith("/api/voicenote/")) {
    return json(res, 200, { note: "dev stub: no WAV here. Run the real console for audio." });
  }

  if (path === "/api/cost") {
    return json(res, 200, { inr_total: 11.4, breakdown: { stt: 4.2, tts: 3.9, llm: 3.3 } });
  }

  return json(res, 404, { error: "not found" });
});

/* ── WebSocket, docs/04 §5. Hand-rolled so the stub stays dependency-free. ─ */

server.on("upgrade", (req, socket) => {
  const url = new URL(req.url ?? "/", `http://${HOST}:${PORT}`);
  const m = /^\/ws\/sessions\/(.+)$/.exec(url.pathname);
  const session = m ? sessions.get(m[1]) : undefined;
  if (!session) {
    socket.end("HTTP/1.1 404 Not Found\r\n\r\n");
    return;
  }

  const key = req.headers["sec-websocket-key"];
  const accept = crypto
    .createHash("sha1")
    .update(`${key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`)
    .digest("base64");
  socket.write(
    "HTTP/1.1 101 Switching Protocols\r\n" +
      "Upgrade: websocket\r\n" +
      "Connection: Upgrade\r\n" +
      `Sec-WebSocket-Accept: ${accept}\r\n\r\n`,
  );
  socket.setNoDelay(true);

  const ws = { socket, buf: Buffer.alloc(0) };
  session.sockets.add(ws);
  // Always the first frame, on every connect and every reconnect.
  wsSend(ws, JSON.stringify({ type: "state_snapshot", state: session.state }));
  if (session.ambiguities.length > 0) {
    wsSend(
      ws,
      JSON.stringify({
        type: "rx_draft",
        lines: session.state.prescription.lines,
        ambiguities: session.ambiguities,
      }),
    );
  }

  socket.on("data", (chunk) => {
    ws.buf = Buffer.concat([ws.buf, chunk]);
    for (const payload of wsDrain(ws)) {
      let frame;
      try {
        frame = JSON.parse(payload);
      } catch {
        continue;
      }
      if (frame.type === "ping") continue;
      if (frame.type === "ptt") {
        console.log(`[mock] ptt ${frame.side} ${frame.state}`);
        // Release is the end-of-turn signal; that is what advances the script.
        if (frame.state === "up") advance(session, frame.side);
      }
    }
  });

  const drop = () => session.sockets.delete(ws);
  socket.on("close", drop);
  socket.on("error", drop);
});

/* ── minimal RFC 6455 framing ──────────────────────────────────────────── */

function wsSend(ws, text) {
  const data = Buffer.from(text, "utf8");
  const len = data.length;
  let header;
  if (len < 126) {
    header = Buffer.from([0x81, len]);
  } else if (len < 65536) {
    header = Buffer.alloc(4);
    header[0] = 0x81;
    header[1] = 126;
    header.writeUInt16BE(len, 2);
  } else {
    header = Buffer.alloc(10);
    header[0] = 0x81;
    header[1] = 127;
    header.writeBigUInt64BE(BigInt(len), 2);
  }
  try {
    ws.socket.write(Buffer.concat([header, data]));
  } catch {
    /* socket gone */
  }
}

/** Pulls complete client frames out of the buffer. Text frames only; no fragments. */
function wsDrain(ws) {
  const out = [];
  for (;;) {
    const b = ws.buf;
    if (b.length < 2) break;
    const opcode = b[0] & 0x0f;
    const masked = (b[1] & 0x80) !== 0;
    let len = b[1] & 0x7f;
    let off = 2;
    if (len === 126) {
      if (b.length < 4) break;
      len = b.readUInt16BE(2);
      off = 4;
    } else if (len === 127) {
      if (b.length < 10) break;
      len = Number(b.readBigUInt64BE(2));
      off = 10;
    }
    const maskLen = masked ? 4 : 0;
    if (b.length < off + maskLen + len) break;
    const mask = masked ? b.subarray(off, off + 4) : null;
    const payload = Buffer.from(b.subarray(off + maskLen, off + maskLen + len));
    if (mask) for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i % 4];
    ws.buf = b.subarray(off + maskLen + len);
    if (opcode === 0x8) {
      ws.socket.end();
      break;
    }
    if (opcode === 0x1) out.push(payload.toString("utf8"));
  }
  return out;
}

server.listen(PORT, HOST, () => {
  console.log(`[mock] DEV STUB for the Clinic Console on http://${HOST}:${PORT}`);
  console.log("[mock] not the console · fake LiveKit token · placeholder QR");
  console.log("[mock] each push-to-talk release advances the canned Tamil script");
});
