import { describe, expect, it } from "vitest";
import fixture from "../../../tests/fixtures/project-contract.json";
import type { StudioProject } from "../../types";
import { inferSaveIntent } from "./projectSaveIntent";

const base = () => structuredClone(fixture) as StudioProject;

describe("project save intent", () => {
  it("selects narrow patches for one supported target", () => {
    const original = base();
    expect(inferSaveIntent(original, { ...original, title: "new" })).toEqual({ kind: "metadata", changes: { title: "new" } });
    expect(inferSaveIntent(original, { ...original, settings: { ...original.settings, speechRate: 1.1 } })).toEqual({ kind: "settings", changes: { speechRate: 1.1 } });
    const line = structuredClone(original);
    line.scenes[0].lines[0].text = "new";
    expect(inferSaveIntent(original, line)).toEqual({ kind: "line", lineId: line.scenes[0].lines[0].id, changes: { text: "new" } });
  });

  it("promotes structural, mixed, and multi-line edits to full", () => {
    const original = base();
    const mixed = structuredClone(original);
    mixed.title = "new";
    mixed.settings.speechRate = 1.1;
    expect(inferSaveIntent(original, mixed).kind).toBe("full");
    const structural = structuredClone(original);
    structural.scenes.reverse();
    expect(inferSaveIntent(original, structural).kind).toBe("full");
  });
});

it.each(["speechRate", "gapSeconds"] as const)("uses a full save when clearing %s, alone or with another edit", (key) => {
  for (const otherEdit of [false, true]) {
    const original = base();
    original.scenes[0].lines[0][key] = 1.5;
    const next = structuredClone(original);
    next.scenes[0].lines[0][key] = undefined;
    if (otherEdit) next.scenes[0].lines[0].enabled = false;
    expect(inferSaveIntent(original, next)).toEqual({ kind: "full" });
  }
});

it("preserves a removed override even when another line contains the remaining edit", () => {
  const original = base();
  original.scenes[0].lines[0].speechRate = 1.5;
  original.scenes[0].lines.push({ ...original.scenes[0].lines[0], id: "other" });
  const next = structuredClone(original);
  delete next.scenes[0].lines[0].speechRate;
  next.scenes[0].lines[1].gapSeconds = 0.2;
  expect(inferSaveIntent(original, next)).toEqual({ kind: "full" });
});

it("preserves a removed setting alongside a supported settings edit", () => {
  const original = base();
  original.settings.lineGap = 1.5;
  const next = structuredClone(original);
  delete next.settings.lineGap;
  next.settings.speechRate = 1.1;
  expect(inferSaveIntent(original, next)).toEqual({ kind: "full" });
});

it("preserves a removed project field alongside a title edit", () => {
  const original = base();
  original.scriptCastContexts = {};
  const next = structuredClone(original);
  delete next.scriptCastContexts;
  next.title = "edited";
  expect(inferSaveIntent(original, next)).toEqual({ kind: "full" });
});
