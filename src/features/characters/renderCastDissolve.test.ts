import { afterEach, expect, it, vi } from "vitest";
import type { CastSnapshot } from "./castSnapshot";
import { renderCastDissolve } from "./renderCastDissolve";

afterEach(() => vi.unstubAllGlobals());

it("reports a drawing failure from a later animation frame", () => {
  let nextFrame!: FrameRequestCallback;
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn((callback: FrameRequestCallback) => {
      nextFrame = callback;
      return 1;
    }),
  );
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  const targetContext = { setTransform: vi.fn(), clearRect: vi.fn(), drawImage: vi.fn(), fillRect: vi.fn(), globalAlpha: 1, fillStyle: "" };
  const sourceContext = { getImageData: vi.fn(() => ({ data: new Uint8ClampedArray([0, 0, 0, 255]) })) };
  const source = { width: 1, height: 1, getContext: vi.fn(() => sourceContext) } as unknown as HTMLCanvasElement;
  const canvas = {
    width: 1,
    height: 1,
    getContext: vi.fn(() => targetContext),
    getBoundingClientRect: vi.fn(() => ({ width: 10, height: 10 })),
  } as unknown as HTMLCanvasElement;
  const snapshot: CastSnapshot = { canvas: source, width: 1, height: 1, left: 0, top: 0 };
  const onFailure = vi.fn();
  renderCastDissolve(canvas, snapshot, onFailure);
  targetContext.fillRect.mockImplementation(() => {
    throw new Error("draw failed");
  });
  nextFrame(performance.now() + 16);
  expect(onFailure).toHaveBeenCalledOnce();
  expect(canvas.width).toBe(0);
  expect(canvas.height).toBe(0);
});

it("ends a caller-specific one-second animation without changing the default", () => {
  let nextFrame!: FrameRequestCallback;
  const requestFrame = vi.fn((callback: FrameRequestCallback) => {
    nextFrame = callback;
    return 1;
  });
  vi.stubGlobal("requestAnimationFrame", requestFrame);
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  const targetContext = { setTransform: vi.fn(), clearRect: vi.fn(), drawImage: vi.fn(), fillRect: vi.fn(), globalAlpha: 1, fillStyle: "" };
  const sourceContext = { getImageData: vi.fn(() => ({ data: new Uint8ClampedArray([0, 0, 0, 255]) })) };
  const source = { width: 1, height: 1, getContext: vi.fn(() => sourceContext) } as unknown as HTMLCanvasElement;
  const canvas = { width: 1, height: 1, getContext: vi.fn(() => targetContext), getBoundingClientRect: vi.fn(() => ({ width: 10, height: 10 })) } as unknown as HTMLCanvasElement;
  const snapshot: CastSnapshot = { canvas: source, width: 1, height: 1, left: 0, top: 0 };
  const start = performance.now();
  renderCastDissolve(canvas, snapshot, undefined, 1000);
  expect(requestFrame).toHaveBeenCalledOnce();
  nextFrame(start + 1001);
  expect(requestFrame).toHaveBeenCalledOnce();
  requestFrame.mockClear();
  const defaultStart = performance.now();
  renderCastDissolve(canvas, snapshot);
  nextFrame(defaultStart + 1001);
  expect(requestFrame).toHaveBeenCalledTimes(2);
});

it("draws fixed 3 CSS pixel grains with one frame loop and a 2500 grain operation cap", () => {
  let nextFrame!: FrameRequestCallback;
  const requestFrame = vi.fn((callback: FrameRequestCallback) => {
    nextFrame = callback;
    return 1;
  });
  vi.stubGlobal("requestAnimationFrame", requestFrame);
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  const targetContext = { setTransform: vi.fn(), clearRect: vi.fn(), drawImage: vi.fn(), fillRect: vi.fn(), globalAlpha: 1, fillStyle: "" };
  const sourceContext = { getImageData: vi.fn(() => ({ data: new Uint8ClampedArray(100 * 100 * 4).fill(255) })) };
  const source = { width: 100, height: 100, getContext: vi.fn(() => sourceContext) } as unknown as HTMLCanvasElement;
  const canvas = { width: 0, height: 0, getContext: vi.fn(() => targetContext), getBoundingClientRect: vi.fn(() => ({ width: 600, height: 300 })) } as unknown as HTMLCanvasElement;
  const snapshots: CastSnapshot[] = [0, 1, 2].map((index) => ({ canvas: source, width: 200, height: 200, left: index * 200, top: 0 }));
  const metrics = vi.fn();
  renderCastDissolve(canvas, snapshots, undefined, 1000, { onMetrics: metrics });
  expect(requestFrame).toHaveBeenCalledOnce();
  expect(targetContext.drawImage).toHaveBeenCalledTimes(3);
  expect(targetContext.fillRect).toHaveBeenCalled();
  expect(targetContext.fillRect.mock.calls.every((args) => args[2] === 3 && args[3] === 3)).toBe(true);
  targetContext.drawImage.mockClear();
  nextFrame(performance.now() + 700);
  expect(targetContext.drawImage).not.toHaveBeenCalled();
  nextFrame(performance.now() + 1001);
  expect(metrics).toHaveBeenCalledWith(expect.objectContaining({ particleCount: expect.any(Number) }));
  expect(metrics.mock.calls[0][0].particleCount).toBeLessThanOrEqual(2500);
  expect(requestFrame).toHaveBeenCalledTimes(2);
});
