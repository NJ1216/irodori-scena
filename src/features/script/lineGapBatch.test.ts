import { describe, expect, it } from "vitest";
import type { DialogueLine, StudioProject } from "../../types";
import { adjustSelectedLineGaps, setSelectedLineGaps } from "./lineGapBatch";

function line(id: string, gapSeconds?: number, cueId?: string): DialogueLine {
  return { id, characterId: "cast", text: id, stageDirection: "", takes: [], selectedTakeId: null, gapSeconds, cueId };
}

function project(lines: DialogueLine[]): StudioProject {
  return { scenes: [{ id: "scene", title: "Scene", lines }], settings: { lineGap: 0.7 } } as StudioProject;
}

describe("adjustSelectedLineGaps", () => {
  it("increments every selected gap from its own explicit or inherited value", () => {
    const updated = adjustSelectedLineGaps(project([line("one"), line("two", 0.9), line("last", 4)]), ["one", "two", "last"], [1]);
    expect(updated.scenes[0].lines.map((item) => item.gapSeconds)).toEqual([0.8, 1, 4]);
  });

  it("updates a simultaneous cue through its gap-owning head only", () => {
    const updated = adjustSelectedLineGaps(project([line("head", 0.2, "cue"), line("tail", undefined, "cue"), line("after"), line("last")]), ["head", "tail", "after"], [-1]);
    expect(updated.scenes[0].lines.map((item) => item.gapSeconds)).toEqual([0.1, undefined, 0.6, undefined]);
  });

  it("sets or resets every selected gap while leaving the final cue unchanged", () => {
    const source = project([line("one", 0.2), line("two", 0.9), line("last", 4)]);
    const set = setSelectedLineGaps(source, ["one", "two", "last"], 1.5);
    expect(set.scenes[0].lines.map((item) => item.gapSeconds)).toEqual([1.5, 1.5, 4]);
    const reset = setSelectedLineGaps(set, ["one", "two"], undefined);
    expect(reset.scenes[0].lines.map((item) => item.gapSeconds)).toEqual([undefined, undefined, 4]);
  });
});
