import { describe, expect, it } from "vitest";
import type { DialogueLine, StudioProject } from "../../types";
import { adjustSelectedLineNumericField, adjustedLineNumericValue, setSelectedLineNumericField } from "./lineNumericBatch";

function line(id: string, patch: Partial<DialogueLine> = {}): DialogueLine {
  return { id, characterId: "cast", text: id, stageDirection: "", takes: [], selectedTakeId: null, ...patch };
}

function project(lines: DialogueLine[]): StudioProject {
  return {
    scenes: [{ id: "scene", title: "Scene", lines }],
    settings: { speechRate: 1, textCfg: 1.5, voiceCfg: 2, captionCfg: 3 },
  } as StudioProject;
}

describe("adjustSelectedLineNumericField", () => {
  it("steps every selected speech rate from its own explicit or inherited value", () => {
    const updated = adjustSelectedLineNumericField(project([line("one"), line("two", { speechRate: 0.9 }), line("three", { speechRate: 1.4 })]), ["one", "two"], "speechRate", [1]);
    expect(updated.scenes[0].lines.map((item) => item.speechRate)).toEqual([1.05, 0.95, 1.4]);
  });

  it("applies a deferred arrow sequence once while preserving each line's clamping", () => {
    const updated = adjustSelectedLineNumericField(project([line("one", { speechRate: 1.95 }), line("two", { speechRate: 0.9 })]), ["one", "two"], "speechRate", [1, 1, -1]);
    expect(updated.scenes[0].lines.map((item) => item.speechRate)).toEqual([1.95, 0.95]);
  });

  it.each([
    ["textCfg", 1.6],
    ["voiceCfg", 2.1],
    ["captionCfg", 3.1],
  ] as const)("steps inherited %s values", (field, expected) => {
    const updated = adjustSelectedLineNumericField(project([line("one"), line("two")]), ["one", "two"], field, [1]);
    expect(updated.scenes[0].lines.map((item) => item[field])).toEqual([expected, expected]);
  });

  it("clamps values to each field's supported range", () => {
    expect(adjustedLineNumericValue("speechRate", 2, 1, 1)).toBe(2);
    expect(adjustedLineNumericValue("speechRate", 0.5, 1, -1)).toBe(0.5);
    expect(adjustedLineNumericValue("textCfg", 10, 3, 1)).toBe(10);
    expect(adjustedLineNumericValue("captionCfg", 0, 3, -1)).toBe(0);
  });
});

describe("setSelectedLineNumericField", () => {
  it("sets the same explicit value on every selected line", () => {
    const updated = setSelectedLineNumericField(project([line("one"), line("two", { voiceCfg: 7 }), line("three")]), ["one", "two"], "voiceCfg", 4.5);
    expect(updated.scenes[0].lines.map((item) => item.voiceCfg)).toEqual([4.5, 4.5, undefined]);
  });

  it("resets every selected line to its shared value", () => {
    const updated = setSelectedLineNumericField(project([line("one", { speechRate: 0.8 }), line("two", { speechRate: 1.4 }), line("three", { speechRate: 1.8 })]), ["one", "two"], "speechRate", undefined);
    expect(updated.scenes[0].lines.map((item) => item.speechRate)).toEqual([undefined, undefined, 1.8]);
  });
});
