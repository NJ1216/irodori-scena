import { describe, expect, it } from "vitest";
import type { DialogueLine, StudioProject } from "../../types";
import { moveProjectLines, movableLineIds, visibleDragGhostCardCount } from "./lineReorder";

const line = (id: string, cueId?: string): DialogueLine => ({ id, cueId, characterId: "cast", text: id, stageDirection: "", takes: [{ id: `take-${id}`, audioUrl: id, seed: 7, quality: "fast", stageDirection: "", createdAt: 1 }], selectedTakeId: `take-${id}` });
const project = (): StudioProject =>
  ({
    id: "project",
    version: 1,
    title: "test",
    revision: 1,
    characters: [],
    candidates: [],
    scenes: [
      { id: "a", title: "A", lines: [line("1"), line("2", "cue"), line("3", "cue"), line("4")] },
      { id: "b", title: "B", lines: [line("5")] },
    ],
    settings: { quality: "fast", sampler: "sway", steps: 16, textCfg: 1, voiceCfg: 1, speechRate: 1, lineGap: 0.7, seed: 1, llmBaseUrl: "", llmModel: "" },
  }) as StudioProject;
const ids = (value: StudioProject) => value.scenes.map((scene) => scene.lines.map((item) => item.id));

describe("line reorder", () => {
  it("shows one ghost card per moved line up to five", () => {
    expect([1, 2, 5, 6].map(visibleDragGhostCardCount)).toEqual([1, 2, 5, 5]);
  });

  it("moves one line up and down without changing its data", () => {
    const source = project();
    const moved = moveProjectLines(source, ["4"], { sceneId: "a", beforeLineId: "1" });
    expect(ids(moved)).toEqual([["4", "1", "2", "3"], ["5"]]);
    expect(moved.scenes[0].lines[0]).toBe(source.scenes[0].lines[3]);
  });

  it("keeps non-contiguous selections in script order across scenes", () => {
    expect(ids(moveProjectLines(project(), ["5", "1"], { sceneId: "b" }))).toEqual([
      ["2", "3", "4"],
      ["1", "5"],
    ]);
  });

  it("supports scene starts, ends, and empty scenes", () => {
    const source = project();
    source.scenes.push({ id: "empty", title: "Empty", lines: [] });
    expect(ids(moveProjectLines(source, ["1"], { sceneId: "empty" }))).toEqual([["2", "3", "4"], ["5"], ["1"]]);
  });

  it("expands any selected cue member to the complete cue", () => {
    expect(movableLineIds(project(), "2", ["2"])).toEqual(["2", "3"]);
    expect(movableLineIds(project(), "1", ["1", "3", "5"])).toEqual(["1", "2", "3", "5"]);
  });

  it("returns the original project for an internal or unchanged drop", () => {
    const source = project();
    expect(moveProjectLines(source, ["2", "3"], { sceneId: "a", beforeLineId: "3" })).toBe(source);
    expect(moveProjectLines(source, ["2", "3"], { sceneId: "a", beforeLineId: "4" })).toBe(source);
  });
});
