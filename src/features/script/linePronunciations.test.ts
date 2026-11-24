import { describe, expect, it } from "vitest";
import { normalizeLinePronunciations, selectionConflict, updatePronunciationsForText } from "./linePronunciations";

const ruby = { id: "ruby-1", start: 0, end: 2, text: "東京", reading: "とうきょう" };

describe("line pronunciations", () => {
  it("uses Unicode code points and follows edits before a reading", () => {
    expect(updatePronunciationsForText("😀東京へ", "😀！東京へ", [{ ...ruby, start: 1, end: 3 }])).toEqual([{ ...ruby, start: 2, end: 4 }]);
  });

  it("removes only a reading touched by an edit", () => {
    const other = { id: "ruby-2", start: 3, end: 5, text: "上京", reading: "じょうきょう" };
    expect(updatePronunciationsForText("東京と上京", "東都と上京", [ruby, other])).toEqual([other]);
  });

  it("rejects overlaps and line breaks but permits adjacent spans", () => {
    expect(selectionConflict("東京大阪", 1, 3, [{ ...ruby, start: 0, end: 2 }])).toContain("重なる");
    expect(selectionConflict("東京\n大阪", 1, 4)).toContain("改行");
    expect(selectionConflict("東京大阪", 2, 4, [{ ...ruby, start: 0, end: 2 }])).toBeNull();
  });

  it("partially accepts valid siblings", () => {
    expect(normalizeLinePronunciations("東京大阪", [ruby, { ...ruby, id: "bad", start: 3, text: "失敗" }])).toEqual([ruby]);
  });
});
