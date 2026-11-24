// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { StudioProject } from "../../types";
import { waitForScriptLineSnapshots } from "./scriptLineCapture";
import { captureScriptLineCanvas } from "./scriptLineCanvasSnapshot";
import { renderCastDissolve } from "../characters/renderCastDissolve";
import { beginScriptLineDeletion, cancelRestoredScriptLineEffects, cancelScriptLineDeletionEffects, finishScriptLineCompaction, hiddenScriptLineIds } from "./scriptLineDeletionMotion";

vi.mock("./scriptLineCanvasSnapshot", () => ({ captureScriptLineCanvas: vi.fn() }));
vi.mock("../characters/renderCastDissolve", () => ({ renderCastDissolve: vi.fn(() => () => {}) }));

function rect(top: number): DOMRect {
  return { x: 20, y: top, left: 20, top, right: 620, bottom: top + 100, width: 600, height: 100, toJSON: () => ({}) } as DOMRect;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(captureScriptLineCanvas).mockImplementation(async (card) => ({ canvas: document.createElement("canvas"), width: 600, height: 100, left: card.getBoundingClientRect().left, top: card.getBoundingClientRect().top }));
  document.body.innerHTML = `<section class="script-canvas"><article class="line-card" data-line-id="one">一</article><article class="line-card" data-line-id="two">二</article><article class="line-card" data-line-id="three">三</article></section>`;
  const canvas = document.querySelector<HTMLElement>(".script-canvas")!;
  vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue(rect(0));
  document.querySelectorAll<HTMLElement>(".line-card").forEach((card, index) => {
    vi.spyOn(card, "getBoundingClientRect").mockReturnValue(rect(index === 1 ? 900 : 20 + index * 120));
  });
});

afterEach(() => {
  vi.runAllTimers();
  vi.useRealTimers();
  document.body.innerHTML = "";
  cancelScriptLineDeletionEffects();
});

it("animates only visible deleted cards while hiding every selected line", async () => {
  await waitForScriptLineSnapshots(["one", "two"]);
  const motion = beginScriptLineDeletion(["one", "two"]);
  expect(hiddenScriptLineIds()).toEqual(new Set(["one", "two"]));
  expect(document.querySelectorAll(".script-deletion-canvas")).toHaveLength(1);
  expect(renderCastDissolve).toHaveBeenCalledOnce();
  expect(renderCastDissolve).toHaveBeenCalledWith(expect.any(HTMLCanvasElement), expect.any(Array), undefined, 1000, expect.objectContaining({ onMetrics: expect.any(Function) }));
  expect(document.querySelector(".script-canvas")).toHaveClass("is-deletion-compacting");
  finishScriptLineCompaction();
  motion.complete();
  expect(hiddenScriptLineIds().size).toBe(0);
  vi.advanceTimersByTime(699);
  expect(document.querySelector(".script-canvas")).toHaveClass("is-deletion-compacting");
  vi.advanceTimersByTime(221);
  expect(document.querySelector(".script-canvas")).not.toHaveClass("is-deletion-compacting");
});

it("moves surviving cards once and removes the effect on rollback", async () => {
  await waitForScriptLineSnapshots(["one"]);
  const survivor = document.querySelector<HTMLElement>('[data-line-id="three"]')!;
  const cancel = vi.fn();
  const animate = vi.fn(() => ({ cancel }) as unknown as Animation);
  survivor.animate = animate;
  const motion = beginScriptLineDeletion(["one"]);
  vi.spyOn(survivor, "getBoundingClientRect").mockReturnValue(rect(40));
  finishScriptLineCompaction();
  expect(animate).toHaveBeenCalledOnce();
  expect(animate).toHaveBeenCalledWith(expect.any(Array), expect.objectContaining({ delay: 700, duration: 220, fill: "backwards" }));
  motion.rollback();
  expect(cancel).toHaveBeenCalledOnce();
  vi.spyOn(survivor, "getBoundingClientRect").mockReturnValue(rect(260));
  finishScriptLineCompaction();
  expect(animate).toHaveBeenLastCalledWith(expect.any(Array), expect.objectContaining({ delay: 0, duration: 220 }));
  expect(document.querySelector(".script-deletion-overlay")).toBeNull();
  expect(hiddenScriptLineIds().size).toBe(0);
});

it("stops an old effect when Undo restores its line", async () => {
  await waitForScriptLineSnapshots(["one"]);
  const motion = beginScriptLineDeletion(["one"]);
  motion.complete();
  const projectWith = (ids: string[]) => ({ scenes: [{ lines: ids.map((id) => ({ id })) }] }) as StudioProject;
  cancelRestoredScriptLineEffects(projectWith(["one", "two"]));
  expect(document.querySelector(".script-deletion-overlay")).not.toBeNull();
  cancelRestoredScriptLineEffects(projectWith(["two"]));
  cancelRestoredScriptLineEffects(projectWith(["one", "two"]));
  expect(document.querySelector(".script-deletion-overlay")).toBeNull();
});
