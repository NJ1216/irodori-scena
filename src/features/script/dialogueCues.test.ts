import { describe, expect, it } from "vitest";
import type { DialogueLine } from "../../types";
import { cueSelectedDuration, effectiveGapSeconds, effectiveUnitStarts, sceneDialogueCues } from "./dialogueCues";

const line = (id: string, cueId?: string): DialogueLine => ({
  id,
  cueId,
  characterId: id,
  text: id,
  stageDirection: "",
  takes: [],
  selectedTakeId: null,
});

describe("dialogue cues", () => {
  it("only combines consecutive matching cue IDs", () => {
    expect(sceneDialogueCues({ lines: [line("a", "x"), line("b", "x"), line("c"), line("d", "x")] }).map((cue) => cue.lines.map((item) => item.id))).toEqual([["a", "b"], ["c"], ["d"]]);
  });
  it("uses the latest offset plus selected take duration", () => {
    const a = line("a", "x");
    a.startOffsetSeconds = 1;
    a.selectedTakeId = "t";
    a.takes = [{ id: "t", audioUrl: "a", seed: 1, quality: "fast", stageDirection: "", createdAt: 1, durationSeconds: 2 }];
    const b = line("b", "x");
    b.startOffsetSeconds = 0.5;
    b.selectedTakeId = "t";
    b.takes = [{ ...a.takes[0], durationSeconds: 4 }];
    expect(cueSelectedDuration(sceneDialogueCues({ lines: [a, b] })[0])).toBe(4.5);
  });
  it("only reports an effective overlap when every cue member has a selected duration", () => {
    const a = line("a", "x");
    expect(cueSelectedDuration(sceneDialogueCues({ lines: [a] })[0])).toBeUndefined();
    expect(effectiveGapSeconds(-4, 2, 0.6)).toBe(-2);
    expect(effectiveGapSeconds(-0.4, 2, 0.6)).toBe(-0.4);
    expect(effectiveUnitStarts([3, 3, 2], [-1, -2]).starts).toEqual([0, 2, 3]);
  });
});
