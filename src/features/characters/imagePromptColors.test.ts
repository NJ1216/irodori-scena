import { describe, expect, it } from "vitest";
import { PROMPT_COLORS } from "./imagePromptColors";

describe("PROMPT_COLORS", () => {
  it("provides more than one hundred named swatches from red through violet", () => {
    expect(PROMPT_COLORS.length).toBeGreaterThanOrEqual(100);
    expect(PROMPT_COLORS.find((color) => color.name === "crimson")?.hex).toBe("#DC143C");
    expect(PROMPT_COLORS.find((color) => color.name === "violet")?.hex).toBe("#8F00FF");
  });
});
