import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import { openCasts } from "./cast-deletion-fixture";

for (const content of ["standard", "long notebook"])
  test(`bounded renderer releases buffers and drawing loop: ${content}`, async ({ page }, info) => {
    await page.setViewportSize({ width: 1600, height: 1000 });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await openCasts(page, false, false, true, content === "long notebook" ? "人の話をよく聞き、穏やかに返事をする。\n".repeat(80) : undefined);
    if (content === "long notebook") {
      await page.getByRole("button", { name: "次の見開き" }).click();
      await expect(page.locator(".cast-notebook-spread h2")).toHaveCount(0);
    }
    const result = await page.evaluate(async () => {
      const snapshotPath = "/src/features/characters/castSnapshot.ts";
      const rendererPath = "/src/features/characters/renderCastDissolve.ts";
      const { captureCastSnapshot, disposeCastSnapshot } = await import(snapshotPath);
      const { renderCastDissolve } = await import(rendererPath);
      const region = document.querySelector<HTMLElement>(".cast-deletion-region")!;
      const captureStart = performance.now();
      const snapshot = await captureCastSnapshot(region, new AbortController().signal);
      const captureMs = performance.now() - captureStart;
      const canvas = document.createElement("canvas");
      canvas.className = "cast-deletion-canvas";
      region.append(canvas);
      const start = performance.now();
      const stop = renderCastDissolve(canvas, snapshot);
      const setupMs = performance.now() - start;
      let previous = performance.now(),
        frame = 0;
      const intervals: number[] = [];
      const sample = (now: number) => {
        intervals.push(now - previous);
        previous = now;
        frame = requestAnimationFrame(sample);
      };
      frame = requestAnimationFrame(sample);
      await new Promise((resolve) => setTimeout(resolve, 2100));
      cancelAnimationFrame(frame);
      const pixel = canvas.getContext("2d")!.getImageData(0, 0, canvas.width, canvas.height).data;
      const cleared = pixel.every((value, index) => index % 4 !== 3 || value === 0);
      stop();
      disposeCastSnapshot(snapshot);
      await new Promise(requestAnimationFrame);
      const released = canvas.width === 0 && snapshot.canvas.width === 0;
      canvas.remove();
      intervals.sort((a, b) => a - b);
      return { captureMs, setupMs, frames: intervals.length, p95FrameMs: intervals[Math.floor(intervals.length * 0.95)], cleared, released };
    });
    await writeFile(info.outputPath("renderer-metrics.json"), JSON.stringify(result));
    expect(result.frames).toBeGreaterThan(2);
    expect(result.cleared).toBe(true);
    expect(result.released).toBe(true);
    expect(errors).toEqual([]);
  });
