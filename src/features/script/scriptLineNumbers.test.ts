import { describe, expect, it } from "vitest";
import { minimumLineNumberWidth, numberedScriptLines } from "./scriptLineNumbers";

describe("script line numbering", () => {
  it("numbers enabled lines across scenes and includes empty lines", () => {
    const project = {
      scenes: [
        {
          id: "a",
          lines: [
            { id: "a1", enabled: true },
            { id: "a2", enabled: false },
          ],
        },
        {
          id: "b",
          lines: [
            { id: "b1", enabled: true },
            { id: "b2", enabled: true },
          ],
        },
      ],
    } as never;
    expect(numberedScriptLines(project).map((item) => item.number)).toEqual([1, null, 2, 3]);
    expect(minimumLineNumberWidth(project)).toBe(3);
  });
});
