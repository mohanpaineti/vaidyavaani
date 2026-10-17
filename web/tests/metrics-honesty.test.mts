/**
 * The guard against zero-for-unknown.
 *
 * Every assertion here exists because the opposite was once true on screen. If
 * one of these fails, a value nobody measured is about to be shown to a judge as
 * a number, or worse, as a green rating. docs/00-HANDOVER §13: "the project's
 * whole credibility rests on the difference between measured and assumed."
 *
 * Runs on node's own test runner with native TypeScript — no new dependency:
 *   npm test
 */

import { test, describe } from "node:test";
import assert from "node:assert/strict";

import {
  BAND_CLASS,
  BAND_GOOD_MS,
  BAND_LABEL,
  UNMEASURED,
  bandFor,
  formatMs,
  formatNumber,
  formatScore,
  isMeasured,
  measuredOnly,
} from "../lib/metrics-format.ts";
import { p90, reduceFrame, emptyView } from "../lib/console-ws.ts";
import { confidenceDigits, isLowConfidence } from "../lib/rx.ts";
import type { RxLine, ServerFrame } from "../lib/types.ts";

/** Everything that can turn up where a metric is expected. */
const HOLES = [null, undefined, NaN] as const;

describe("bandFor never rates a value it was not given", () => {
  for (const hole of HOLES) {
    test(`bandFor(${String(hole)}) is null, not "good"`, () => {
      // `null <= 900` is **true** in JavaScript. That one coercion is how an
      // untimed turn used to come out green.
      assert.equal(bandFor(hole), null);
    });
  }

  test("a real measurement still bands normally", () => {
    assert.equal(bandFor(800), "good");
    assert.equal(bandFor(BAND_GOOD_MS), "good");
    assert.equal(bandFor(1000), "slow");
    assert.equal(bandFor(1500), "over");
  });

  test("zero is a measurement and bands as one — the fix is not to hide zeros", () => {
    // 0 ms really measured would be absurd, but it is not *missing*, and
    // conflating the two is the bug in the other direction.
    assert.equal(bandFor(0), "good");
  });

  test("the colour and label tables have no entry a null could reach", () => {
    assert.deepEqual(Object.keys(BAND_CLASS).sort(), ["good", "over", "slow"]);
    assert.deepEqual(Object.keys(BAND_LABEL).sort(), ["good", "over", "slow"]);
  });
});

describe("formatters never invent a digit", () => {
  for (const hole of HOLES) {
    test(`formatMs(${String(hole)}) says so in words`, () => {
      const out = formatMs(hole);
      assert.equal(out, UNMEASURED);
      assert.match(out, /[a-z]/i);
      assert.doesNotMatch(out, /\d/, "an unmeasured value must contain no digit");
    });

    test(`formatNumber(${String(hole)}) contains no digit`, () => {
      assert.doesNotMatch(formatNumber(hole), /\d/);
    });

    test(`formatScore(${String(hole)}) is not 0.00`, () => {
      assert.doesNotMatch(formatScore(hole), /\d/);
    });
  }

  test("measured values format as themselves", () => {
    assert.equal(formatMs(840), "840 ms");
    assert.equal(formatNumber(840), "840");
    assert.equal(formatScore(0.58), "0.58");
    assert.equal(formatScore(0), "0.00", "a scored zero is a score, and prints");
  });

  test("isMeasured / measuredOnly agree about the holes", () => {
    assert.equal(isMeasured(0), true);
    for (const hole of HOLES) assert.equal(isMeasured(hole), false);
    assert.deepEqual(measuredOnly([840, null, undefined, NaN, 0]), [840, 0]);
  });
});

describe("aggregates are computed over measurements only", () => {
  test("p90 skips holes rather than counting them as zero", () => {
    // Counted as 0, the hole would drag p90 down and turn a slow call green.
    assert.equal(p90([1000, null, 1000, undefined]), 1000);
  });

  test("p90 of nothing is null, not 0", () => {
    assert.equal(p90([]), null);
    assert.equal(p90([null, undefined]), null);
  });
});

describe("the metric frame survives a null latency", () => {
  test("a null reply_latency_ms is stored as a hole, not coerced", () => {
    // console/app/metrics.py:latest_frame returns exactly this when the dev log
    // has no record it recognises.
    const frame: ServerFrame = { type: "metric", reply_latency_ms: null, stages: {} };
    const view = reduceFrame(emptyView, frame);
    assert.equal(view.metrics.length, 1);
    assert.equal(view.metrics[0].reply_latency_ms, null);
    assert.equal(bandFor(view.metrics[0].reply_latency_ms), null);
  });

  test("p90 over a mix of real and null frames uses only the real ones", () => {
    const frames: ServerFrame[] = [
      { type: "metric", reply_latency_ms: 900, stages: {} },
      { type: "metric", reply_latency_ms: null, stages: {} },
      { type: "metric", reply_latency_ms: 1100, stages: {} },
    ];
    const view = frames.reduce(reduceFrame, emptyView);
    assert.equal(p90(view.metrics.map((m) => m.reply_latency_ms)), 1100);
  });
});

describe("an unscored prescription line is not a confident one", () => {
  const line = (confidence: number | null): RxLine => ({
    id: "rx_1",
    drug_text: "Paracetamol",
    strength_value: 500,
    strength_unit: "mg",
    form: "tablet",
    schedule: { morning: 1, afternoon: 0, night: 1 },
    food_relation: "after_food",
    duration_days: 5,
    notes: null,
    confidence,
    confirmed: false,
  });

  test("confidenceDigits on a null score does not throw", () => {
    // `line.confidence.toFixed(2)` threw here, and took the doctor's whole half
    // down with it. The console types confidence as `float | None`.
    assert.doesNotThrow(() => confidenceDigits(line(null)));
  });

  test("a null score renders as a word, never 0.00", () => {
    const out = confidenceDigits(line(null));
    assert.doesNotMatch(out, /\d/);
    assert.equal(confidenceDigits(line(0.58)), "0.58");
  });

  test("a null score is treated as low confidence, on purpose", () => {
    assert.equal(isLowConfidence(line(null)), true);
    assert.equal(isLowConfidence(line(0.58)), true);
    assert.equal(isLowConfidence(line(0.94)), false);
  });
});
