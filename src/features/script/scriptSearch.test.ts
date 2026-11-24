import { describe, expect, it } from "vitest";
import { findScriptMatches, replaceLineMatches } from "./scriptSearch";

describe("script search", () => {
  it("finds literal, case-insensitive, non-overlapping matches including disabled lines", () => {
    const project = {
      scenes: [
        {
          id: "s",
          lines: [
            { id: "a", text: "Ababa", enabled: true },
            { id: "b", text: "AB", enabled: false },
          ],
        },
      ],
    } as never;
    expect(findScriptMatches(project, "ab")).toEqual([
      { lineId: "a", start: 0, end: 2 },
      { lineId: "a", start: 2, end: 4 },
      { lineId: "b", start: 0, end: 2 },
    ]);
  });

  it("replaces backward, shifts unaffected readings, and removes overlapping readings", () => {
    const result = replaceLineMatches(
      "東京と大阪",
      [
        { id: "tokyo", start: 0, end: 2, text: "東京", reading: "とうきょう" },
        { id: "osaka", start: 3, end: 5, text: "大阪", reading: "おおさか" },
      ],
      [{ start: 0, end: 2 }],
      "東京都",
    );
    expect(result.text).toBe("東京都と大阪");
    expect(result.pronunciations).toEqual([{ id: "osaka", start: 4, end: 6, text: "大阪", reading: "おおさか" }]);
  });
});
