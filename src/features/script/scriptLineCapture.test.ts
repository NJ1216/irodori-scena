// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { clearPreparedScriptLineSnapshots, prepareScriptLineSnapshots, takeScriptLineSnapshot, waitForScriptLineSnapshots } from "./scriptLineCapture";
import { captureScriptLineCanvas } from "./scriptLineCanvasSnapshot";
import { particleDeletionDiagnostics } from "../shared/particleDeletionDiagnostics";

vi.mock("./scriptLineCanvasSnapshot", () => ({ captureScriptLineCanvas: vi.fn() }));
const rect = { x: 20, y: 20, left: 20, top: 20, right: 620, bottom: 120, width: 600, height: 100, toJSON: () => ({}) } as DOMRect;
beforeEach(() => {
  vi.useFakeTimers();
  document.body.innerHTML = '<section class="script-canvas"><article class="line-card" data-line-id="line-one"><img src="/avatar.png">本文</article></section>';
  vi.spyOn(document.querySelector<HTMLElement>(".script-canvas")!, "getBoundingClientRect").mockReturnValue(rect);
  vi.spyOn(document.querySelector<HTMLElement>(".line-card")!, "getBoundingClientRect").mockReturnValue(rect);
});
afterEach(() => {
  clearPreparedScriptLineSnapshots();
  vi.runAllTimers();
  vi.useRealTimers();
  document.body.innerHTML = "";
  vi.clearAllMocks();
});

it("waits for the first-click card capture before deleting", async () => {
  const image = { canvas: document.createElement("canvas"), width: 600, height: 100, left: 20, top: 20 };
  let finish!: (value: typeof image) => void;
  vi.mocked(captureScriptLineCanvas).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  prepareScriptLineSnapshots(["line-one"]);
  let settled = false;
  const waiting = waitForScriptLineSnapshots(["line-one"]).then(() => {
    settled = true;
  });
  await vi.advanceTimersByTimeAsync(20);
  expect(settled).toBe(false);
  finish(image);
  await waiting;
  const snapshot = takeScriptLineSnapshot("line-one");
  expect(snapshot).toBe(image);
});

it("rejects failed or stalled preparation instead of allowing deletion", async () => {
  vi.mocked(captureScriptLineCanvas).mockRejectedValueOnce(new Error("image unavailable"));
  prepareScriptLineSnapshots(["line-one"]);
  await expect(waitForScriptLineSnapshots(["line-one"])).rejects.toThrow("image unavailable");
  expect(particleDeletionDiagnostics().at(-2)).toMatchObject({ target: "line", itemId: "line-one", phase: "unknown", outcome: "failed" });
  clearPreparedScriptLineSnapshots();
  vi.mocked(captureScriptLineCanvas).mockImplementation(() => new Promise(() => {}));
  prepareScriptLineSnapshots(["line-one"]);
  const waiting = expect(waitForScriptLineSnapshots(["line-one"])).rejects.toThrow("タイムアウト");
  await vi.advanceTimersByTimeAsync(10_000);
  await waiting;
});

it("logs a capture cleared before it finished as cancelled, not failed", async () => {
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
  const image = { canvas: document.createElement("canvas"), width: 600, height: 100, left: 20, top: 20 };
  let finish!: (value: typeof image) => void;
  vi.mocked(captureScriptLineCanvas).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  prepareScriptLineSnapshots(["line-one"]);
  clearPreparedScriptLineSnapshots();
  finish(image);
  await vi.advanceTimersByTimeAsync(20);
  expect(particleDeletionDiagnostics().at(-1)).toMatchObject({ target: "line", itemId: "line-one", phase: "aborted", outcome: "cancelled", error: "cleared" });
  expect(consoleError).not.toHaveBeenCalled();
});
