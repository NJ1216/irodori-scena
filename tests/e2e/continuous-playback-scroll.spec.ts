import { expect, test } from "@playwright/test";
import { testToneWav } from "./audio-fixtures";
import { installMockApi } from "./mock-api";

test("makes the first protected overlap ready before starting the audio clock", async ({ page }) => {
  const project = await installMockApi(page, { generatedTake: true, completeTakes: true, lineCount: 3 });
  project.scenes[0].lines.forEach((line, index) => {
    line.gapSeconds = index < 2 ? -0.1 : 0;
  });
  const events: string[] = [];
  await page.exposeFunction("recordPlaybackEvent", (event: string) => events.push(event));
  await page.addInitScript(() => {
    const original = AudioBufferSourceNode.prototype.start;
    AudioBufferSourceNode.prototype.start = function observedStart(...args) {
      void (window as unknown as { recordPlaybackEvent: (event: string) => Promise<void> }).recordPlaybackEvent("source.start");
      return original.apply(this, args as [number, number?, number?]);
    };
  });
  project.scenes[0].lines.forEach((line) => {
    line.takes[0].durationSeconds = 0.4;
  });
  const prepared: Array<{ events: Array<{ lineId: string; startFrame: number; endFrame: number }>; startFrame: number; endFrame: number; sampleRate: number }> = [];
  page.on("request", (request) => {
    if (request.url().endsWith("/timeline/plan")) events.push("plan");
    if (request.url().endsWith("/timeline/prepare")) events.push("prepare");
  });
  page.on("response", async (response) => {
    if (response.url().endsWith("/timeline/prepare")) prepared.push(...(await response.json()).intervals);
  });
  let releaseAudio!: () => void;
  const audioReady = new Promise<void>((resolve) => {
    releaseAudio = resolve;
  });
  await page.route("**/api/media/timeline-e2e-*.wav", async (route) => {
    events.push("interval-audio");
    await audioReady;
    const frames = Number(new URL(route.request().url()).pathname.match(/timeline-e2e-(\d+)\.wav$/)?.[1]);
    await route.fulfill({ body: testToneWav(frames / 8000), contentType: "audio/wav" });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "▶ 連続再生" }).click();
  await expect.poll(() => events.includes("interval-audio")).toBe(true);
  expect(events).not.toContain("source.start");
  await expect.poll(() => prepared.length).toBe(1);
  const first = prepared[0];
  expect(first.endFrame - first.startFrame).toBeLessThanOrEqual(first.sampleRate);
  expect(first.events.map((event) => event.lineId)).toEqual(project.scenes[0].lines.map((line) => line.id));
  // Both negative gaps belong to the prepared interval, before any source starts.
  for (let index = 1; index < first.events.length; index++) {
    expect(first.events[index].startFrame).toBe(first.events[index - 1].endFrame - first.sampleRate * 0.1);
  }
  releaseAudio();
  await expect.poll(() => events.includes("source.start")).toBe(true);
  expect(events.indexOf("plan")).toBeLessThan(events.indexOf("prepare"));
  expect(events.indexOf("prepare")).toBeLessThan(events.indexOf("interval-audio"));
  expect(events.indexOf("interval-audio")).toBeLessThan(events.indexOf("source.start"));
});

test("centers the first simultaneous line during hover-enabled continuous playback", async ({ page }) => {
  await installMockApi(page, { simultaneousCue: true, generatedTake: true, completeTakes: true });
  await page.route("**/api/media/cue-mix.wav", (route) => route.fulfill({ body: testToneWav(5), contentType: "audio/wav" }));
  await page.addInitScript(() => {
    const scrolled: Array<{ lineId?: string; block?: ScrollLogicalPosition }> = [];
    Object.assign(window, { __scrolledPlaybackLines: scrolled });
    HTMLElement.prototype.scrollIntoView = function scrollIntoView(options?: boolean | ScrollIntoViewOptions) {
      scrolled.push({ lineId: this.dataset.lineId, block: typeof options === "object" ? options.block : undefined });
    };
  });
  await page.goto("/");
  await page.getByRole("button", { name: "▶ 連続再生" }).click();
  const playing = page.locator(".line-card.is-cue-member.is-playing");
  await expect(playing).toHaveCount(2);
  const firstLineId = await playing.first().getAttribute("data-line-id");
  await page.mouse.move(0, 0);
  await page.getByRole("button", { name: "■ 停止" }).hover();
  await expect
    .poll(() =>
      page.evaluate(() =>
        (
          window as typeof window & {
            __scrolledPlaybackLines: Array<{ lineId?: string; block?: string }>;
          }
        ).__scrolledPlaybackLines.at(-1),
      ),
    )
    .toEqual({ lineId: firstLineId, block: "center" });
});

test("toggles persistent playback Follow with F and cancels it on active manual scroll", async ({ page }) => {
  await installMockApi(page, { generatedTake: true, completeTakes: true });
  const wav = testToneWav(5);
  for (const path of ["take-e2e-1.wav", "take-e2e-2.wav"]) {
    await page.route(`**/api/media/**/${path}`, (route) => route.fulfill({ body: wav, contentType: "audio/wav" }));
  }
  await page.goto("/");
  const playback = page.locator(".play-toggle");
  await page.getByRole("button", { name: "▶ 連続再生" }).click();
  await page.mouse.move(0, 0);
  await playback.hover();
  await expect(playback).toHaveClass(/auto-scroll-active/);
  await page.mouse.move(0, 0);
  await expect(playback).not.toHaveClass(/auto-scroll-active/);
  await page.keyboard.press("f");
  await expect(playback).toHaveClass(/auto-scroll-active/);
  await playback.hover();
  await page.mouse.move(0, 0);
  await expect(playback).toHaveClass(/auto-scroll-active/);
  await page.mouse.wheel(0, 100);
  await expect(playback).not.toHaveClass(/auto-scroll-active/);
  await page.keyboard.press("f");
  await expect(playback).toHaveClass(/auto-scroll-active/);

  await page.keyboard.press("Space");
  await expect(page.getByRole("button", { name: "▶ 連続再生" })).toHaveClass(/auto-scroll-active/);
  await page.mouse.wheel(0, 100);
  await expect(page.getByRole("button", { name: "▶ 連続再生" })).toHaveClass(/auto-scroll-active/);

  await page.keyboard.press("Space");
  await expect(page.getByRole("button", { name: "■ 停止" })).toHaveClass(/auto-scroll-active/);
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("button", { name: "■ 停止" })).not.toHaveClass(/auto-scroll-active/);
});

test("toggles exclusive auto-generation Follow with R while idle", async ({ page }) => {
  await installMockApi(page, { generatedTake: true, completeTakes: true });
  await page.goto("/");
  const playback = page.locator(".play-toggle");
  const autoGeneration = page.locator(".auto-generate-button");
  await autoGeneration.click();
  await expect(autoGeneration).toHaveAttribute("aria-pressed", "false");
  await page.getByRole("button", { name: "台本", exact: true }).click();
  await page.keyboard.press("r");
  await expect(autoGeneration).toHaveClass(/auto-scroll-active/);
  await expect(playback).not.toHaveClass(/auto-scroll-active/);
  await expect(autoGeneration).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("r");
  await expect(autoGeneration).not.toHaveClass(/auto-scroll-active/);
  await expect(autoGeneration).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("r");
  await expect(autoGeneration).toHaveAttribute("aria-pressed", "false");

  await page.keyboard.press("r");
  await expect(autoGeneration).toHaveClass(/auto-scroll-active/);
  await page.mouse.wheel(0, 100);
  await expect(autoGeneration).not.toHaveClass(/auto-scroll-active/);
  await expect(autoGeneration).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("r");
  await expect(autoGeneration).toHaveAttribute("aria-pressed", "false");
});

test("waits for a negative gap save before preparing overlap playback", async ({ page }) => {
  await installMockApi(page, { generatedTake: true, completeTakes: true });
  const wav = testToneWav();
  for (const path of ["take-e2e-1.wav", "take-e2e-2.wav", "overlap.wav"]) {
    await page.route(`**/api/media/**/${path}`, (route) => route.fulfill({ body: wav, contentType: "audio/wav" }));
  }
  let releaseSave: (() => void) | undefined;
  let reportSaveStarted: (() => void) | undefined;
  const saveStarted = new Promise<void>((resolve) => {
    reportSaveStarted = resolve;
  });
  const saveReleased = new Promise<void>((resolve) => {
    releaseSave = resolve;
  });
  let overlapRequested = false;
  await page.route("**/api/lines/line-1", async (route) => {
    if (route.request().method() !== "PATCH") return route.fallback();
    reportSaveStarted?.();
    await saveReleased;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ revision: 2 }) });
  });
  await page.route("**/api/project/timeline/prepare", async (route) => {
    overlapRequested = true;
    await route.fallback();
  });
  await page.goto("/");
  await page.getByLabel("発話行ごとの発話間隔（秒）").first().fill("-0.5");
  const startPlayback = page.getByRole("button", { name: "▶ 連続再生" }).click();

  await saveStarted;
  expect(overlapRequested).toBe(false);
  await expect(page.locator(".notice-screen-reader-text")).toHaveText("変更を保存しています。完了後に連続再生を開始します。");
  releaseSave?.();
  await startPlayback;
  await expect.poll(() => overlapRequested).toBe(true);
});

test("completes zero-gap lines through scheduled buffer playback", async ({ page }) => {
  await installMockApi(page, { generatedTake: true, completeTakes: true });
  const wav = testToneWav();
  for (const path of ["take-e2e-1.wav", "take-e2e-2.wav"]) {
    await page.route(`**/api/media/**/${path}`, (route) => route.fulfill({ body: wav, contentType: "audio/wav" }));
  }
  await page.goto("/");
  const gap = page.getByLabel("発話行ごとの発話間隔（秒）").first();
  await gap.fill("0");
  await gap.press("Enter");
  await page.getByRole("button", { name: "▶ 連続再生" }).click();

  await expect(page.locator(".notice-screen-reader-text")).toHaveText("連続再生が終わりました。", { timeout: 5_000 });
});

test("completes negative-gap playback through the shared media fetch path", async ({ page }) => {
  await installMockApi(page, { generatedTake: true, completeTakes: true });
  const wav = testToneWav();
  for (const path of ["take-e2e-1.wav", "take-e2e-2.wav", "overlap.wav"]) {
    await page.route(`**/api/media/**/${path}`, (route) => route.fulfill({ body: wav, contentType: "audio/wav" }));
  }
  await page.goto("/");
  const gap = page.getByLabel("発話行ごとの発話間隔（秒）").first();
  await gap.fill("-0.1");
  await gap.press("Enter");
  await page.getByRole("button", { name: "▶ 連続再生" }).click();

  await expect(page.locator(".notice-screen-reader-text")).toHaveText("連続再生が終わりました。", { timeout: 5_000 });
});

test("following the last line keeps the page itself in place", async ({ page }) => {
  // 2026-11-28: the hidden labels of the per-line gap controls were positioned against the page, not
  // the script canvas, so they stretched the page below the window. Centering the last line during
  // continuous playback then scrolled the whole page and left a blank band under the script.
  await page.setViewportSize({ width: 1280, height: 900 });
  await installMockApi(page, { lineCount: 30, generatedTake: true, completeTakes: true });
  await page.goto("/");
  const last = page.locator('[data-line-id="line-30"]');
  await expect(last).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBe(await page.evaluate(() => document.documentElement.clientHeight));
  await last.evaluate((element) => element.scrollIntoView({ behavior: "instant", block: "center" }));
  expect(await page.evaluate(() => document.documentElement.scrollTop)).toBe(0);
  const canvas = page.locator(".script-canvas");
  expect(await canvas.evaluate((element) => element.scrollHeight - element.clientHeight - element.scrollTop)).toBeLessThanOrEqual(1);
});
