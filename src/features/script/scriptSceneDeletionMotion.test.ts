// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { StudioProject } from "../../types";
import { captureScriptSceneCanvas } from "./scriptLineCanvasSnapshot";
import { renderCastDissolve } from "../characters/renderCastDissolve";
import { prepareScriptSceneSnapshot, waitForScriptSceneSnapshot } from "./scriptSceneCapture";
import { beginScriptSceneDeletion, cancelRestoredScriptSceneEffects, cancelScriptSceneDeletionEffects, finishScriptSceneCompaction, hiddenScriptSceneIds, oneLineCardHeightCssPx, sceneParticleBudget } from "./scriptSceneDeletionMotion";

vi.mock("./scriptLineCanvasSnapshot", () => ({ captureScriptSceneCanvas: vi.fn() }));
vi.mock("../characters/renderCastDissolve", () => ({ gpuParticleLimit: 2500, maximumGpuParticleLimit: 10_000, renderCastDissolve: vi.fn(() => () => {}) }));

function rect(top: number): DOMRect {
  return { x: 20, y: top, left: 20, top, right: 620, bottom: top + 100, width: 600, height: 100, toJSON: () => ({}) } as DOMRect;
}

beforeEach(() => {
  vi.useFakeTimers();
  document.body.innerHTML = '<section class="script-canvas"><article class="scene-box" data-scene-id="one">一</article><article class="scene-box" data-scene-id="two">二</article></section>';
  vi.spyOn(document.querySelector<HTMLElement>(".script-canvas")!, "getBoundingClientRect").mockReturnValue(rect(0));
  document.querySelectorAll<HTMLElement>(".scene-box").forEach((scene, index) => {
    vi.spyOn(scene, "getBoundingClientRect").mockReturnValue(rect(20 + index * 120));
  });
  vi.mocked(captureScriptSceneCanvas).mockImplementation(async (_, crop) => ({ canvas: document.createElement("canvas"), width: crop.width, height: crop.height, left: crop.left, top: crop.top }));
});

afterEach(() => {
  cancelScriptSceneDeletionEffects();
  vi.runAllTimers();
  vi.useRealTimers();
  document.body.innerHTML = "";
  vi.clearAllMocks();
});

it("scales scene grains from the measured one-line card height and caps them at 10000", () => {
  expect(oneLineCardHeightCssPx).toBe(145);
  expect(sceneParticleBudget(100)).toBe(2500);
  expect(sceneParticleBudget(145)).toBe(2500);
  expect(sceneParticleBudget(464)).toBe(8000);
  expect(sceneParticleBudget(580)).toBe(10_000);
});

it("waits for captured visible pixels and leaves the scene intact when preparation fails", async () => {
  vi.mocked(captureScriptSceneCanvas).mockRejectedValueOnce(new Error("image unavailable"));
  prepareScriptSceneSnapshot("one");
  await expect(waitForScriptSceneSnapshot("one")).rejects.toThrow("image unavailable");
  expect(hiddenScriptSceneIds().size).toBe(0);
  expect(document.querySelector(".script-deletion-overlay")).toBeNull();
});

it("animates the visible scene, compacts survivors, and stops on Undo", async () => {
  prepareScriptSceneSnapshot("one");
  await waitForScriptSceneSnapshot("one");
  const survivor = document.querySelector<HTMLElement>('[data-scene-id="two"]')!;
  const cancel = vi.fn();
  const animate = vi.fn(() => ({ cancel }) as unknown as Animation);
  survivor.animate = animate;
  const motion = beginScriptSceneDeletion("one");
  expect(hiddenScriptSceneIds()).toEqual(new Set(["one"]));
  expect(document.querySelectorAll(".script-deletion-canvas")).toHaveLength(1);
  expect(renderCastDissolve).toHaveBeenCalledWith(expect.any(HTMLCanvasElement), expect.any(Object), undefined, 1000, expect.objectContaining({ particleLimit: 2500 }));
  vi.spyOn(survivor, "getBoundingClientRect").mockReturnValue(rect(40));
  finishScriptSceneCompaction();
  expect(animate).toHaveBeenCalledOnce();
  expect(animate).toHaveBeenCalledWith(expect.any(Array), expect.objectContaining({ delay: 700, duration: 220, fill: "backwards" }));
  motion.complete();
  const project = (ids: string[]) => ({ scenes: ids.map((id) => ({ id })) }) as StudioProject;
  cancelRestoredScriptSceneEffects(project(["two"]));
  cancelRestoredScriptSceneEffects(project(["one", "two"]));
  expect(cancel).toHaveBeenCalledOnce();
  expect(document.querySelector(".script-deletion-overlay")).toBeNull();
});
