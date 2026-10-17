/**
 * The structural half of the guard.
 *
 * `metrics-honesty.test.mts` proves the formatters are honest. This file proves
 * the components still *use* them — because the way this bug comes back is not
 * someone breaking `formatMs`, it is someone adding a tile and interpolating the
 * raw value next to a unit, exactly as every tile here once did.
 *
 * Two mechanisms, deliberately different in kind:
 *   · a source scan for the shapes that render a raw metric, and
 *   · compile-time assertions (checked by `npm run typecheck`, not at runtime)
 *     that the contract types still admit the nulls the console really sends.
 *     Narrowing `reply_latency_ms` back to `number` breaks the build here.
 */

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import type { RxLine, ServerFrame, StageTimings } from "../lib/types.ts";
import type { FailoverEvent, MetricSample } from "../lib/console-ws.ts";

const WEB = dirname(dirname(fileURLToPath(import.meta.url)));
const read = (rel: string) => readFileSync(join(WEB, rel), "utf8");

/** Every file that renders a metric, a latency, a band or a score. */
const METRIC_RENDERERS = [
  "components/MetricsHUD.tsx",
  "components/SessionHeader.tsx",
  "components/PrescriptionCard.tsx",
];

describe("no component interpolates a raw metric", () => {
  /**
   * `{x.foo_ms}` or `{x}ms` next to a unit. Each of these was literally on
   * screen before this commit: `{last.reply_latency_ms}` under a "ms" span,
   * `{lastLatency}ms` in the header, `{ms === undefined ? "—" : `${ms}ms`}` in
   * the stage tiles. React prints nothing for null, so they rendered a bare
   * "ms" under the word "good".
   */
  const RAW_RENDERS: { pattern: RegExp; why: string }[] = [
    {
      // `(?![A-Z0-9_]+\})` lets the band legend through: `{BAND_GOOD_MS}ms` is a
      // SCREAMING_CASE constant describing the scale, not a measurement.
      pattern: /(?<!\$)\{(?![A-Z0-9_]+\})[A-Za-z_$][\w.$?]*\}\s*ms\b/,
      why: "a value interpolated straight next to a `ms` unit",
    },
    {
      pattern: /\$\{[A-Za-z_$][\w.$?]*\}ms/,
      why: "a template literal that appends `ms` to a possibly-missing value",
    },
    {
      // `(?<!\$)` keeps this to JSX interpolation. `${l.confidence}` inside a
      // template literal is a memo key, not something a doctor reads.
      pattern: /(?<!\$)\{[\w.$?]*(?:latency|_ms|confidence)[\w.$?]*\}/,
      why: "a latency or confidence rendered without going through a formatter",
    },
    {
      pattern: /\.(?:toFixed)\(/,
      why: "`.toFixed` on a field the console types as nullable — it throws on null",
    },
    {
      pattern: /(?:latency|_ms|confidence)[\w.$?]*\s*(?:\?\?|\|\|)\s*0\b/,
      why: "a metric defaulted to 0 — the exact zero-for-unknown this guards",
    },
  ];

  for (const file of METRIC_RENDERERS) {
    const src = read(file);
    for (const { pattern, why } of RAW_RENDERS) {
      test(`${file}: ${why}`, () => {
        const hit = src.split("\n").find((line) => pattern.test(line));
        assert.equal(
          hit,
          undefined,
          `${file} has ${why}:\n    ${hit}\n` +
            "  Route it through lib/metrics-format.ts instead — formatMs, formatNumber,\n" +
            "  formatScore or bandFor. An unmeasured number must never reach the screen\n" +
            "  as a digit or as a rating band.",
        );
      });
    }
  }

  test("the HUD and the header both go through the formatter module", () => {
    for (const file of ["components/MetricsHUD.tsx", "components/SessionHeader.tsx"]) {
      assert.match(
        read(file),
        /from "@\/lib\/metrics-format"/,
        `${file} must take its bands and formatting from lib/metrics-format.ts`,
      );
    }
  });
});

describe("the teach-back panel does not paint an unchecked verdict green", () => {
  const src = read("components/TeachBackPanel.tsx");

  test("`not_mentioned` has its own shell class, not the match one", () => {
    // A two-way `mismatch ? red : green` painted "the patient never repeated the
    // dose" in the colour that means "the patient got it right".
    assert.match(src, /not_mentioned:\s*"border-slate/);
    assert.doesNotMatch(
      src,
      /bad\s*\?\s*"border-red[^"]*"\s*:\s*"border-emerald/,
      "a two-way band makes not_mentioned read as a pass",
    );
  });
});

/*
 * ── Compile-time assertions ────────────────────────────────────────────────
 *
 * These run nowhere. They fail in `npm run typecheck` and `npm run build`, which
 * is the point: they pin the nullability of the fields the console genuinely
 * sends as null, so a future "tidy-up" back to `number` cannot land quietly.
 *
 *   confidence          console/app/models.py:RxLine  → float | None
 *   reply_latency_ms    console/app/metrics.py:latest_frame → None when no record
 *   stages.*            omitted entirely, or null (docs/00-HANDOVER §12)
 *   gap_ms              same frame family, same treatment
 */

const _unscoredLine: Pick<RxLine, "confidence"> = { confidence: null };

const _untimedFrame: ServerFrame = {
  type: "metric",
  reply_latency_ms: null,
  stages: {},
};

const _nullStages: StageTimings = { stt: null, llm_ttft: null, tts_first_audio: null };

const _untimedSample: Pick<MetricSample, "reply_latency_ms"> = { reply_latency_ms: null };

const _untimedFailover: FailoverEvent = { from: "indic", to: "multi_backup", gap_ms: null };

void _unscoredLine;
void _untimedFrame;
void _nullStages;
void _untimedSample;
void _untimedFailover;
