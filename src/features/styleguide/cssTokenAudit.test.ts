import { describe, expect, it } from "vitest";
import { findUntokenizedCssValues, summarizeCssTokenAudit } from "./cssTokenAudit";

describe("CSS token audit", () => {
  it("lists hard-coded colors and dimensions but ignores token references", () => {
    const items = findUntokenizedCssValues(".card { color: #123456; padding: 12px; background: var(--scena-surface); }", "example.css");
    expect(items).toEqual(expect.arrayContaining([expect.objectContaining({ category: "色", selector: ".card", property: "color" }), expect.objectContaining({ category: "余白", selector: ".card", property: "padding" })]));
    expect(items).toHaveLength(2);
    expect(summarizeCssTokenAudit(items)).toEqual({ 色: 1, 余白: 1, 角丸: 0, 固定寸法: 0 });
  });
});
