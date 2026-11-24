import { describe, expect, it } from "vitest";
import type { StudioProject } from "../../types";
import { modifiedLinePointerSelection } from "./linePointerSelection";

const project = {
  scenes: [
    { id: "one", title: "一", lines: [{ id: "a" }, { id: "b" }] },
    { id: "two", title: "二", lines: [{ id: "c" }, { id: "d" }] },
  ],
} as StudioProject;

const cueProject = {
  scenes: [{ id: "one", title: "一", lines: [{ id: "a", cueId: "cue" }, { id: "b", cueId: "cue" }, { id: "c" }, { id: "d" }] }],
} as StudioProject;

describe("modifiedLinePointerSelection", () => {
  it("selects one continuous range across scenes with Shift", () => {
    expect(
      modifiedLinePointerSelection({
        project,
        clickedLineId: "d",
        focusedLineId: "b",
        selectedLineIds: ["b"],
        anchorLineId: "b",
        modifiers: { shiftKey: true, altKey: false },
      }),
    ).toEqual({ focusedLineId: "d", selectedLineIds: ["b", "c", "d"], anchorLineId: "b" });
  });

  it("toggles sparse lines with Option and keeps script order", () => {
    expect(
      modifiedLinePointerSelection({
        project,
        clickedLineId: "c",
        focusedLineId: "a",
        selectedLineIds: ["d", "a"],
        anchorLineId: "a",
        modifiers: { shiftKey: false, altKey: true },
      }),
    ).toEqual({ focusedLineId: "c", selectedLineIds: ["a", "c", "d"], anchorLineId: "c" });
  });

  it("moves focus to a surviving line when Option removes the focused line", () => {
    expect(
      modifiedLinePointerSelection({
        project,
        clickedLineId: "c",
        focusedLineId: "c",
        selectedLineIds: ["a", "c"],
        anchorLineId: "a",
        modifiers: { shiftKey: false, altKey: true },
      }),
    ).toEqual({ focusedLineId: "a", selectedLineIds: ["a"], anchorLineId: "c" });
  });

  it("selects and toggles simultaneous speech as one stable cue", () => {
    expect(
      modifiedLinePointerSelection({
        project: cueProject,
        clickedLineId: "b",
        focusedLineId: "c",
        selectedLineIds: ["c"],
        anchorLineId: "c",
        modifiers: { shiftKey: false, altKey: true },
      }),
    ).toEqual({ focusedLineId: "b", selectedLineIds: ["a", "b", "c"], anchorLineId: "b" });
    expect(
      modifiedLinePointerSelection({
        project: cueProject,
        clickedLineId: "b",
        focusedLineId: "b",
        selectedLineIds: ["a", "b", "c"],
        anchorLineId: "b",
        modifiers: { shiftKey: false, altKey: true },
      }),
    ).toEqual({ focusedLineId: "c", selectedLineIds: ["c"], anchorLineId: "b" });
  });
});
