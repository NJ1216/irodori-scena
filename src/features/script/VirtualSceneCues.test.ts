import { describe, expect, it } from "vitest";
import { includePinnedCueIndexes } from "./virtualCueRange";

describe("includePinnedCueIndexes", () => {
  it("keeps both the focused cue and an off-screen Follow target mounted", () => {
    expect(includePinnedCueIndexes([0, 1, 2], 1, 220)).toEqual([0, 1, 2, 220]);
  });

  it("deduplicates pinned indexes already in or shared with the visible range", () => {
    expect(includePinnedCueIndexes([8, 9, 10], 9, 9)).toEqual([8, 9, 10]);
  });
});
