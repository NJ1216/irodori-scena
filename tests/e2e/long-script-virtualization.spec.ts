import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

for (const width of [1280, 1440]) {
  test(`later scenes keep their opening lines visible at ${width}px`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({ width, height: 960 });
    await installMockApi(page, { sceneLineCounts: [21, 32, 210] });
    await page.goto("/");
    const scenes = page.locator(".scene-box");
    await expect(scenes).toHaveCount(3);
    for (const [index, firstLine] of [
      [1, 22],
      [2, 54],
      [0, 1],
    ]) {
      await scenes.nth(index).evaluate((scene) => {
        const canvas = scene.closest<HTMLElement>(".script-canvas")!;
        canvas.scrollTop += scene.getBoundingClientRect().top - canvas.getBoundingClientRect().top;
      });
      const first = page.locator(`[data-line-id="line-${firstLine}"]`);
      await expect(first).toBeInViewport();
      await expect
        .poll(async () => {
          const header = await scenes.nth(index).locator(".scene-header").boundingBox();
          const line = await first.boundingBox();
          return line && header ? line.y - header.y - header.height : Infinity;
        })
        .toBeLessThan(100);
    }
    expect(errors).toEqual([]);
  });
}

test("five thousand lines render a bounded cue window and keep scrolling reachable", async ({ page }) => {
  const writes: Array<{ method: string; path: string; body: unknown }> = [];
  page.on("request", (request) => {
    if (["PATCH", "PUT"].includes(request.method())) writes.push({ method: request.method(), path: new URL(request.url()).pathname, body: request.postDataJSON() });
  });
  await installMockApi(page, { lineCount: 5_000 });
  await page.goto("/");
  const stack = page.locator(".line-stack[data-virtualized=true]");
  await expect(stack).toHaveCount(1);
  await expect.poll(() => page.locator(".line-card").count()).toBeLessThan(40);
  const firstEditor = page.locator('[data-line-id="line-1"] .line-text-editor');
  await firstEditor.click();
  await firstEditor.fill("長い台本でも入力途中を保持");
  await expect(firstEditor).toHaveText("長い台本でも入力途中を保持");
  expect(writes).toEqual([]);
  await firstEditor.blur();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toMatchObject({ method: "PATCH", path: "/api/lines/line-1", body: { changes: { text: "長い台本でも入力途中を保持", pronunciations: [] } } });
  expect(JSON.stringify(writes[0].body)).not.toContain('"scenes"');
  const canvas = page.locator(".script-canvas");
  await canvas.evaluate((element) => element.scrollTo({ top: element.scrollHeight }));
  await expect(page.locator('[data-line-id="line-5000"]')).toBeInViewport();
  await expect(page.locator('[data-line-id="line-1"]')).toHaveCount(1);
  await expect(page.locator('[data-line-id="line-5000"] .line-text-editor')).toHaveText("うん。少し遠回りして帰ろうか。 5000");
  await expect.poll(() => page.locator(".line-card").count()).toBeLessThan(40);
});

test("measures expanded dialogue and simultaneous cue groups without overlap", async ({ page }) => {
  await installMockApi(page, { lineCount: 250, simultaneousCue: true });
  await page.goto("/");
  const first = page.locator('[data-line-id="line-1"]');
  await first.locator(".line-text-editor").fill("長い台詞を折り返して表示します。".repeat(40));
  await first.locator(".line-text-editor").blur();
  const secondGroup = page.locator('[data-line-id="line-3"]');
  await expect
    .poll(async () => {
      const tail = await page.locator('[data-line-id="line-2"]').boundingBox();
      const next = await secondGroup.boundingBox();
      return next && tail ? next.y - tail.y - tail.height : -1;
    })
    .toBeGreaterThanOrEqual(0);
  await expect
    .poll(async () => {
      const tail = await page.locator('[data-line-id="line-2"]').boundingBox();
      const next = await secondGroup.boundingBox();
      return next && tail ? next.y - tail.y - tail.height : Infinity;
    })
    .toBeLessThan(100);
});
