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

  it("keeps offsets on the original text when lowercasing changes the length", () => {
    const project = { scenes: [{ id: "s", lines: [{ id: "a", text: "İab ABか", enabled: true }] }] } as never;
    const matches = findScriptMatches(project, "ab");
    expect(matches).toEqual([
      { lineId: "a", start: 1, end: 3 },
      { lineId: "a", start: 4, end: 6 },
    ]);
    expect(replaceLineMatches("İab ABか", undefined, matches, "X").text).toBe("İX Xか");
  });

  it("matches Japanese text and regular-expression characters literally", () => {
    const project = { scenes: [{ id: "s", lines: [{ id: "a", text: "東京と東京。a.b a+b", enabled: true }] }] } as never;
    expect(findScriptMatches(project, "東京")).toEqual([
      { lineId: "a", start: 0, end: 2 },
      { lineId: "a", start: 3, end: 5 },
    ]);
    expect(findScriptMatches(project, "a.b")).toEqual([{ lineId: "a", start: 6, end: 9 }]);
    expect(findScriptMatches(project, "A+B")).toEqual([{ lineId: "a", start: 10, end: 13 }]);
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
