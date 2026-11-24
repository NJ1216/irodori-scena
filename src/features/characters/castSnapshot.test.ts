import { afterEach, expect, it, vi } from "vitest";
import { castSnapshotTimeoutMs, prepareCastSnapshot, snapshotSvgDocument } from "./castSnapshot";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("keeps the XHTML clone as the foreignObject root", () => {
  const svg = snapshotSvgDocument('<section xmlns="http://www.w3.org/1999/xhtml">ink</section>', 100, 50);
  expect(svg).toContain('<foreignObject width="100%" height="100%"><section xmlns="http://www.w3.org/1999/xhtml">ink</section></foreignObject>');
  expect(svg).not.toContain('<foreignObject width="100%" height="100%"><div');
});

it("starts capture in reduced-motion mode", async () => {
  vi.stubGlobal("matchMedia", () => ({ matches: true }));
  const region = document.createElement("div");
  const find = vi.spyOn(region, "querySelector");
  expect(await prepareCastSnapshot(region, new AbortController().signal)).toBeNull();
  expect(find).toHaveBeenCalled();
});

it("times out stalled font preparation and resolves without blocking deletion", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  const fonts = Object.getOwnPropertyDescriptor(document, "fonts");
  Object.defineProperty(document, "fonts", { configurable: true, value: { ready: new Promise(() => {}) } });
  const region = document.createElement("div");
  region.innerHTML = '<article class="cast-notebook-spread"></article>';
  vi.spyOn(region.firstElementChild!, "getBoundingClientRect").mockReturnValue({ width: 100, height: 100 } as DOMRect);
  try {
    const result = prepareCastSnapshot(region, new AbortController().signal);
    await vi.advanceTimersByTimeAsync(castSnapshotTimeoutMs);
    expect(await result).toBeNull();
    expect(vi.getTimerCount()).toBe(0);
  } finally {
    if (fonts) Object.defineProperty(document, "fonts", fonts);
    else Reflect.deleteProperty(document, "fonts");
  }
});

it("aborts capture when the view is left", async () => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  const controller = new AbortController();
  controller.abort();
  const region = document.createElement("div");
  const find = vi.spyOn(region, "querySelector");
  expect(await prepareCastSnapshot(region, controller.signal)).toBeNull();
  expect(find).not.toHaveBeenCalled();
});
