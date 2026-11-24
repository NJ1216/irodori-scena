import { afterEach, expect, it, vi } from "vitest";
import { observeResizeAfterLayout } from "./observeResizeAfterLayout";

afterEach(() => vi.unstubAllGlobals());

it("coalesces notifications after layout and cancels pending writes on cleanup", () => {
  let notify!: () => void;
  const disconnect = vi.fn();
  const observe = vi.fn();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        notify = callback;
      }
      observe = observe;
      disconnect = disconnect;
    },
  );
  const frames = new Map<number, FrameRequestCallback>();
  let sequence = 0;
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frames.set(++sequence, callback);
    return sequence;
  });
  vi.stubGlobal("cancelAnimationFrame", (frame: number) => frames.delete(frame));
  const update = vi.fn();
  const element = document.createElement("div");
  const stop = observeResizeAfterLayout(update, [element]);
  expect(observe).toHaveBeenCalledWith(element);
  notify();
  notify();
  expect(update).not.toHaveBeenCalled();
  expect(frames.size).toBe(1);
  const [frame, callback] = [...frames][0];
  frames.delete(frame);
  callback(0);
  expect(update).toHaveBeenCalledOnce();
  notify();
  stop();
  expect(frames.size).toBe(0);
  expect(disconnect).toHaveBeenCalledOnce();
});
