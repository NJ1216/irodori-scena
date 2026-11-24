import { describe, expect, it } from "vitest";
import { autoGenerationDisabled } from "./autoGenerationState";

describe("autoGenerationDisabled", () => {
  it("unlocks auto-generation after a cancelled export reaches a terminal state", () => {
    expect(autoGenerationDisabled("export", true)).toBe(true);
    expect(autoGenerationDisabled(null, true)).toBe(false);
  });

  it("allows enabling while a single line is synthesizing", () => {
    expect(autoGenerationDisabled("line_42", false)).toBe(false);
  });

  it("allows turning the setting off or on while another local task is active", () => {
    expect(autoGenerationDisabled("candidates", false)).toBe(false);
  });
});
