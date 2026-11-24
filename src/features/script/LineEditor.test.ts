import { describe, expect, it } from "vitest";

import { normalizeTargetDuration } from "./targetDuration";

describe("target duration normalization", () => {
  it("rounds copied and manually entered durations to tenths", () => {
    expect(normalizeTargetDuration(5.54)).toBe(5.5);
    expect(normalizeTargetDuration(5.56)).toBe(5.6);
  });

  it("clamps values to the Irodori-TTS range", () => {
    expect(normalizeTargetDuration(0.1)).toBe(0.5);
    expect(normalizeTargetDuration(40)).toBe(30);
  });
});
