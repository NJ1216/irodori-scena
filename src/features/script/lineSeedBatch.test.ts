import { expect, it } from "vitest";
import type { StudioProject } from "../../types";
import { setSelectedLineSeeds } from "./lineSeedBatch";

const project = {
  scenes: [
    { id: "scene-1", lines: [{ id: "line-1", fixedSeed: 11 }, { id: "line-2" }] },
    { id: "scene-2", lines: [{ id: "line-3", fixedSeed: 33, manualSeed: 44 }] },
  ],
} as StudioProject;

it("applies one seed edit to selected lines across scenes", () => {
  const updated = setSelectedLineSeeds(project, ["line-1", "line-3"], { fixedSeed: 99, manualSeed: 123 });
  expect(updated.scenes[0].lines[0]).toMatchObject({ fixedSeed: 99, manualSeed: 123 });
  expect(updated.scenes[0].lines[1]).toEqual(project.scenes[0].lines[1]);
  expect(updated.scenes[1].lines[0]).toMatchObject({ fixedSeed: 99, manualSeed: 123 });
});

it("removes fixed and manual seeds from every selected line", () => {
  const updated = setSelectedLineSeeds(project, ["line-1", "line-3"], { fixedSeed: undefined, manualSeed: undefined });
  expect(updated.scenes[0].lines[0].fixedSeed).toBeUndefined();
  expect(updated.scenes[1].lines[0].fixedSeed).toBeUndefined();
  expect(updated.scenes[1].lines[0].manualSeed).toBeUndefined();
});
