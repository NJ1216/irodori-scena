import { describe, expect, it } from "vitest";

import { notebookActionSpacerHeight } from "./cast-notebook-layout";

describe("notebookActionSpacerHeight", () => {
  it("uses only complete ruled lines without returning a negative height", () => {
    expect(
      notebookActionSpacerHeight({
        contentEnd: 224,
        lastLineTop: 224,
        ruleHeight: 28,
      }),
    ).toBe(0);
    expect(
      notebookActionSpacerHeight({
        contentEnd: 140,
        lastLineTop: 224,
        ruleHeight: 28,
      }),
    ).toBe(84);
    expect(
      notebookActionSpacerHeight({
        contentEnd: 141,
        lastLineTop: 224,
        ruleHeight: 28,
      }),
    ).toBe(56);
    expect(
      notebookActionSpacerHeight({
        contentEnd: 252,
        lastLineTop: 224,
        ruleHeight: 28,
      }),
    ).toBe(0);
  });
});
