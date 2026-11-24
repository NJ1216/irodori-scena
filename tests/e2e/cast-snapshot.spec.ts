import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import { openCasts } from "./cast-deletion-fixture";

for (const avatar of [false, true]) {
  test(`notebook capture preserves transparent paper and content (avatar: ${avatar})`, async ({ page }, info) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await openCasts(page, false, false, avatar);
    await page.locator(".cast-notebook-spread").screenshot({ path: info.outputPath("source-notebook.png") });
    const result = await page.evaluate(async () => {
      const path = "/src/features/characters/castSnapshot.ts";
      const { captureCastSnapshot, disposeCastSnapshot } = await import(path);
      const start = performance.now();
      const snapshot = await captureCastSnapshot(document.querySelector(".cast-deletion-region"), new AbortController().signal);
      const duration = performance.now() - start;
      const context = snapshot.canvas.getContext("2d");
      const pixels = context.getImageData(0, 0, snapshot.canvas.width, snapshot.canvas.height).data;
      let opaque = 0,
        white = 0,
        pink = 0;
      for (let index = 0; index < pixels.length; index += 4) {
        if (pixels[index + 3] === 0) continue;
        opaque++;
        if (pixels[index] === 255 && pixels[index + 1] === 255 && pixels[index + 2] === 255) white++;
        if (pixels[index] > 200 && pixels[index + 1] < 100 && pixels[index + 2] < 150) pink++;
      }
      const image = snapshot.canvas.toDataURL();
      const title = document.querySelector(".cast-notebook-spread h2")!.getBoundingClientRect();
      const spread = document.querySelector(".cast-notebook-spread")!.getBoundingClientRect();
      const sx = snapshot.canvas.width / snapshot.width,
        sy = snapshot.canvas.height / snapshot.height;
      let underTitleInk = 0;
      for (let y = Math.ceil((title.bottom - spread.top + 2) * sy); y < (title.bottom - spread.top + 24) * sy; y++) {
        for (let x = Math.floor((title.left - spread.left) * sx); x < (title.right - spread.left) * sx; x++) {
          if (pixels[(y * snapshot.canvas.width + x) * 4 + 3]) underTitleInk++;
        }
      }
      const cornerAlpha = pixels[3];
      const total = pixels.length / 4;
      disposeCastSnapshot(snapshot);
      // Counts are measured in CSS pixel area; the renderer may downsample its bitmap.
      const pixelArea = sx * sy;
      return { duration, opaque: opaque / pixelArea, white: white / pixelArea, pink: pink / pixelArea, underTitleInk, cornerAlpha, total: total / pixelArea, image, released: snapshot.canvas.width === 0 };
    });
    await writeFile(info.outputPath("transparent-notebook.png"), Buffer.from(result.image.split(",")[1], "base64"));
    await writeFile(info.outputPath("capture-metrics.json"), JSON.stringify({ ...result, image: undefined }));
    expect(result.cornerAlpha).toBe(0);
    // Missing lang="ja" changed WebKit font fallback and wrapped the final name glyph.
    expect(result.underTitleInk).toBe(0);
    expect(result.opaque).toBeGreaterThan(1000);
    expect(result.opaque / result.total).toBeLessThan(0.25);
    expect(result.released).toBe(true);
    if (avatar) {
      expect(result.white).toBeGreaterThan(1000);
      expect(result.pink).toBeGreaterThan(5000);
    }
  });
}
