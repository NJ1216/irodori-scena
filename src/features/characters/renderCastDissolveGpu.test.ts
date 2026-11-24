// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import type { CastSnapshot } from "./castSnapshot";
import { createParticleGpuLayer } from "./particleDissolveGpu";
import { renderCastDissolve } from "./renderCastDissolve";

vi.mock("./particleDissolveGpu", () => ({ createParticleGpuLayer: vi.fn() }));
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

function setup() {
  const source = document.createElement("canvas");
  source.width = 100;
  source.height = 100;
  vi.spyOn(source, "getContext").mockReturnValue({ getImageData: () => ({ data: new Uint8ClampedArray(100 * 100 * 4).fill(255) }) } as unknown as CanvasRenderingContext2D);
  const parent = document.createElement("div");
  const canvas = document.createElement("canvas");
  parent.append(canvas);
  document.body.append(parent);
  vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({ width: 600, height: 400 } as DOMRect);
  const snapshot: CastSnapshot = { canvas: source, width: 600, height: 400, left: 0, top: 0 };
  let callback!: FrameRequestCallback;
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn((next: FrameRequestCallback) => {
      callback = next;
      return 1;
    }),
  );
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  return { canvas, source, snapshot, next: (time: number) => callback(time) };
}

it("keeps a separate fading background and caps slow GPU frames at 2500 grains", () => {
  const { canvas, source, snapshot, next } = setup();
  const layer = document.createElement("canvas");
  const draw = vi.fn((_elapsed: number, _visible: number, _retireFrom: number, _alpha: number, _motionScale: number) => true);
  const dispose = vi.fn(() => layer.remove());
  vi.mocked(createParticleGpuLayer).mockImplementation((reference, groups) => {
    reference.parentElement!.append(layer);
    const count = groups.reduce((sum, group) => sum + group.particles.length, 0);
    expect(count).toBe(2500);
    return { canvas: layer, count, draw, dispose };
  });
  const metrics = vi.fn();
  const start = performance.now();
  const stop = renderCastDissolve(canvas, snapshot, undefined, 1000, { onMetrics: metrics });
  expect(source).toHaveClass("particle-deletion-background");
  expect(source.style.animationDuration).toBe("650ms");
  expect(canvas.style.display).toBe("none");
  for (let index = 1; index <= 16; index++) next(start + index * 30);
  expect(draw.mock.calls.every((args) => args[4] === 0.5)).toBe(true);
  expect(draw.mock.calls.every((args) => args[1] === 2500)).toBe(true);
  next(start + 600);
  stop();
  expect(dispose).toHaveBeenCalledOnce();
  expect(source.isConnected).toBe(false);
  expect(canvas.style.display).toBe("");
  expect(metrics).toHaveBeenCalledWith(expect.objectContaining({ renderer: "webgl2", initialParticleCount: expect.any(Number), particleCount: expect.any(Number) }));
  expect(metrics.mock.calls[0][0].particleCount).toBe(2500);
});

it("accepts a scene-specific GPU budget above the ordinary 2500 grain limit", () => {
  const { canvas, snapshot } = setup();
  const counts: number[] = [];
  vi.mocked(createParticleGpuLayer).mockImplementation((_reference, groups) => {
    counts.push(groups.reduce((sum, group) => sum + group.particles.length, 0));
    return { canvas: document.createElement("canvas"), count: counts.at(-1)!, draw: vi.fn(() => true), dispose: vi.fn() };
  });
  const stop = renderCastDissolve(canvas, snapshot, undefined, 1000, { particleLimit: 8000 });
  expect(counts).toEqual([8000]);
  stop();
  const stopCapped = renderCastDissolve(canvas, snapshot, undefined, 1000, { particleLimit: 20_000 });
  expect(counts).toEqual([8000, 10_000]);
  stopCapped();
});

it("limits the Canvas2D fallback to 2500 grains for a large scene", () => {
  const { canvas, snapshot } = setup();
  const context = { setTransform: vi.fn(), clearRect: vi.fn(), fillRect: vi.fn(), drawImage: vi.fn(), globalAlpha: 1, fillStyle: "" };
  vi.spyOn(canvas, "getContext").mockReturnValue(context as unknown as CanvasRenderingContext2D);
  vi.mocked(createParticleGpuLayer).mockReturnValue(null);
  const metrics = vi.fn();
  const stop = renderCastDissolve(canvas, snapshot, undefined, 1000, { particleLimit: 10_000, onMetrics: metrics });
  expect(context.fillRect).toHaveBeenCalledTimes(2500);
  stop();
  expect(metrics).toHaveBeenCalledWith(expect.objectContaining({ renderer: "canvas2d", initialParticleCount: 2500, particleCount: 2500, fallbackReason: "webgl2-unavailable" }));
});

it("switches to the visible 2D canvas if GPU drawing fails later", () => {
  const { canvas, snapshot, next } = setup();
  const context = { setTransform: vi.fn(), clearRect: vi.fn(), fillRect: vi.fn(), drawImage: vi.fn(), globalAlpha: 1, fillStyle: "" };
  vi.spyOn(canvas, "getContext").mockReturnValue(context as unknown as CanvasRenderingContext2D);
  const layer = document.createElement("canvas");
  const dispose = vi.fn(() => layer.remove());
  vi.mocked(createParticleGpuLayer).mockImplementation((reference, groups) => {
    reference.parentElement!.append(layer);
    return { canvas: layer, count: groups.reduce((sum, group) => sum + group.particles.length, 0), draw: vi.fn().mockReturnValueOnce(true).mockReturnValueOnce(false), dispose };
  });
  const failed = vi.fn();
  const metrics = vi.fn();
  const start = performance.now();
  const stop = renderCastDissolve(canvas, snapshot, failed, 1000, { onMetrics: metrics });
  next(start + 16);
  expect(dispose).toHaveBeenCalledOnce();
  expect(canvas.style.display).toBe("");
  expect(context.fillRect).toHaveBeenCalled();
  expect(context.drawImage).not.toHaveBeenCalled();
  expect(failed).not.toHaveBeenCalled();
  stop();
  expect(metrics).toHaveBeenCalledWith(expect.objectContaining({ renderer: "canvas2d", fallbackReason: "webgl2-render-failed" }));
});

it("keeps the captured DOM fade visible when neither drawing context is available", () => {
  const { canvas, source, snapshot } = setup();
  vi.mocked(createParticleGpuLayer).mockReturnValue(null);
  vi.spyOn(canvas, "getContext").mockReturnValue(null);
  const metrics = vi.fn();
  const stop = renderCastDissolve(canvas, snapshot, undefined, 1000, { onMetrics: metrics });
  expect(source.isConnected).toBe(true);
  expect(source.style.animationDuration).toBe("650ms");
  stop();
  expect(metrics).toHaveBeenCalledWith(expect.objectContaining({ renderer: "dom", particleCount: 0, fallbackReason: "canvas-unavailable" }));
  expect(source.isConnected).toBe(false);
});
