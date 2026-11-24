import { expect, test, type CDPSession, type Page } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { installMockApi } from "../e2e/mock-api";

/**
 * Interaction benchmark (Chromium + mock API). Each operation is repeated and reports:
 *  visibleMs  - action start until the expected UI is present and painted (2 rAF)
 *  settleMs   - action start until every finite CSS animation/transition has ended
 *  worstFrame - longest rAF gap inside the settle window (ms)
 *  jank       - frames slower than 25 ms inside the settle window
 *  cpu*       - main-thread script/layout/style/task time from CDP Performance.getMetrics
 * Chromium on the mock API is not the Tauri WebView; use it only to compare before/after.
 */
const REPEATS = Number(process.env.BENCH_REPEATS ?? 9);
const OUT = process.env.BENCH_OUT;
type Sample = { visibleMs: number; settleMs: number; worstFrame: number; jank: number; scriptMs: number; layoutMs: number; styleMs: number; taskMs: number; longTasks: number };
const results: Record<string, Sample[]> = {};

async function installProbe(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as { __b: unknown };
    w.__b = {
      long: 0,
      start(): void {
        const s = this as unknown as { long: number; frames: number[]; t0: number; stop: boolean };
        s.long = 0;
        s.frames = [];
        s.stop = false;
        s.t0 = performance.now();
        let last = performance.now();
        const tick = (now: number) => {
          s.frames.push(now - last);
          last = now;
          if (!s.stop) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      },
    };
    new PerformanceObserver((list) => {
      (w.__b as { long: number }).long += list.getEntries().length;
    }).observe({ entryTypes: ["longtask"] });
  });
}

async function cdpMetrics(cdp: CDPSession) {
  const { metrics } = await cdp.send("Performance.getMetrics");
  const m = Object.fromEntries(metrics.map((x) => [x.name, x.value]));
  return { script: m.ScriptDuration, layout: m.LayoutDuration, style: m.RecalcStyleDuration, task: m.TaskDuration };
}

async function measure(page: Page, cdp: CDPSession, name: string, action: () => Promise<void>, ready: () => Promise<void>) {
  await page.evaluate(() => (window as unknown as { __b: { start(): void } }).__b.start());
  const before = await cdpMetrics(cdp);
  const t0 = await page.evaluate(() => performance.now());
  await action();
  await ready();
  const visibleMs =
    (await page.evaluate(async () => {
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      return performance.now();
    })) - t0;
  const settleAt = await page.evaluate(async () => {
    const finite = () => document.getAnimations().filter((a) => a.effect?.getComputedTiming().iterations !== Infinity && a.playState === "running");
    const deadline = performance.now() + 3000;
    while (finite().length && performance.now() < deadline) await new Promise((r) => requestAnimationFrame(r));
    await new Promise((r) => requestAnimationFrame(r));
    const b = (window as unknown as { __b: { frames: number[]; stop: boolean; long: number } }).__b;
    b.stop = true;
    return { now: performance.now(), frames: b.frames.slice(1), long: b.long };
  });
  const after = await cdpMetrics(cdp);
  (results[name] ??= []).push({
    visibleMs,
    settleMs: settleAt.now - t0,
    worstFrame: Math.max(0, ...settleAt.frames),
    jank: settleAt.frames.filter((f) => f > 25).length,
    scriptMs: (after.script - before.script) * 1000,
    layoutMs: (after.layout - before.layout) * 1000,
    styleMs: (after.style - before.style) * 1000,
    taskMs: (after.task - before.task) * 1000,
    longTasks: settleAt.long,
  });
}

const median = (v: number[]) => [...v].sort((a, b) => a - b)[Math.floor((v.length - 1) / 2)];
const p95 = (v: number[]) => [...v].sort((a, b) => a - b)[Math.floor((v.length - 1) * 0.95)];

async function boot(page: Page, lineCount: number) {
  await installMockApi(page, { lineCount });
  await page.goto("/");
  await expect(page.locator(".line-card").first()).toBeVisible();
  await installProbe(page);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Performance.enable");
  return cdp;
}

async function repeat(n: number, fn: () => Promise<void>) {
  for (let i = 0; i < n; i += 1) await fn();
}
const frame = (page: Page) => page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));

test.afterAll(() => {
  const animRows = Object.entries(results)
    .filter(([name]) => name.startsWith("anim:"))
    .map(([name, s]) => {
      const f = (pick: (x: Sample) => number) => Number(median(s.map(pick)).toFixed(2));
      return { name, n: s.length, frameAvgMs: f((x) => x.visibleMs), worstFrameMs: f((x) => x.worstFrame), jankFrames: f((x) => x.jank), scriptMs: f((x) => x.scriptMs), paintMs: f((x) => x.layoutMs), rasterMs: f((x) => x.styleMs), layoutMs: f((x) => x.taskMs) };
    });
  const rows = Object.entries(results)
    .filter(([name]) => !name.startsWith("anim:"))
    .map(([name, s]) => {
      const f = (pick: (x: Sample) => number, agg = median) => Number(agg(s.map(pick)).toFixed(2));
      return {
        name,
        n: s.length,
        visibleMedian: f((x) => x.visibleMs),
        visibleP95: f((x) => x.visibleMs, p95),
        settleMedian: f((x) => x.settleMs),
        worstFrameP95: f((x) => x.worstFrame, p95),
        jankMedian: f((x) => x.jank),
        scriptMedian: f((x) => x.scriptMs),
        layoutMedian: f((x) => x.layoutMs),
        styleMedian: f((x) => x.styleMs),
        taskMedian: f((x) => x.taskMs),
        longTasksTotal: s.reduce((a, x) => a + x.longTasks, 0),
      };
    });
  console.log("BENCH_TABLE\n" + ["name", "n", "visMed", "visP95", "settleMed", "worstFrameP95", "jank", "scriptMs", "layoutMs", "styleMs", "taskMs", "longTasks"].join("\t"));
  for (const r of rows) console.log(Object.values(r).join("\t"));
  if (animRows.length) {
    console.log("ANIM_TABLE (2 s window, summed trace time in ms)\n" + ["name", "n", "frameAvg", "worstFrame", "jank", "script", "paint", "raster", "layout"].join("\t"));
    for (const r of animRows) console.log(Object.values(r).join("\t"));
  }
  if (OUT) writeFileSync(OUT, JSON.stringify({ repeats: REPEATS, rows, animRows, raw: results }, null, 2));
});

for (const lineCount of [30, 300]) {
  test("navigation and overlays with " + lineCount + " lines", async ({ page }) => {
    test.setTimeout(240_000);
    const cdp = await boot(page, lineCount);
    const tag = "@" + lineCount;
    const tab = (label: string) => page.getByRole("button", { name: label, exact: true }).first();
    const goTab = async (label: string, marker: string) => {
      await measure(
        page,
        cdp,
        "tab:" + label + tag,
        () => tab(label).click(),
        () => expect(page.locator(marker).first()).toBeVisible(),
      );
      await tab("台本").click();
      await expect(page.locator(".line-card").first()).toBeVisible();
      await frame(page);
    };
    await goTab("キャスト", ".cast-notebook, [class*=cast]");
    await repeat(REPEATS, () => goTab("キャスト", ".cast-notebook, [class*=cast]"));
    await repeat(REPEATS, () => goTab("辞書", "[class*=dictionary]"));
    await repeat(REPEATS, () => goTab("設定", "[class*=settings]"));
    results["tab:キャスト" + tag]?.shift();

    await repeat(REPEATS, async () => {
      await measure(
        page,
        cdp,
        "search-open" + tag,
        () => page.evaluate(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "f", code: "KeyF", metaKey: true, bubbles: true }))),
        () => expect(page.getByRole("search")).toBeVisible(),
      );
      await page.keyboard.press("Escape");
      await expect(page.getByRole("search")).toHaveCount(0);
      await frame(page);
    });

    await repeat(REPEATS, async () => {
      await measure(
        page,
        cdp,
        "line-jump-overlay" + tag,
        () => page.keyboard.type(".2"),
        () => expect(page.getByRole("status", { name: "発話行番号へ移動" })).toBeVisible(),
      );
      await page.keyboard.press("Escape");
      await frame(page);
    });

    const projectMenu = tab("プロジェクト");
    await repeat(Math.min(REPEATS, 5), async () => {
      await measure(
        page,
        cdp,
        "open:プロジェクトメニュー" + tag,
        () => projectMenu.click(),
        () => expect(tab("台本読み込み")).toBeVisible(),
      );
      await page.keyboard.press("Escape");
      await frame(page);
    });
    for (const label of ["台本読み込み", "AI演出"]) {
      await repeat(Math.min(REPEATS, 5), async () => {
        await projectMenu.click();
        await expect(tab(label)).toBeVisible();
        await measure(
          page,
          cdp,
          "open-dialog:" + label + tag,
          () => tab(label).click(),
          () => expect(page.locator(".modal").first()).toBeVisible(),
        );
        await page.keyboard.press("Escape");
        await expect(page.locator(".modal")).toHaveCount(0);
        await frame(page);
      });
    }
    await repeat(Math.min(REPEATS, 5), async () => {
      await measure(
        page,
        cdp,
        "open:エクスポートメニュー" + tag,
        () => page.getByRole("button", { name: /^エクスポート/ }).click(),
        () => expect(page.locator("button", { hasText: "音声・字幕・台本" }).first()).toBeVisible(),
      );
      await page.keyboard.press("Escape");
      await frame(page);
    });
  });
}

test("typing, selection and scrolling in a 1000-line script", async ({ page }) => {
  test.setTimeout(240_000);
  const cdp = await boot(page, 1000);
  const editor = page.locator(".line-text-editor").first();
  await editor.click();
  await repeat(REPEATS, async () => {
    await measure(
      page,
      cdp,
      "type-20-chars@1000",
      () => page.keyboard.type("あいうえおかきくけこさしすせそたちつてと", { delay: 0 }),
      () => expect(editor).toBeFocused(),
    );
    await page.keyboard.press("Meta+a");
    await page.keyboard.press("Backspace");
    await frame(page);
  });
  await repeat(REPEATS, async () => {
    await measure(
      page,
      cdp,
      "scroll-2400px-in-40-steps@1000",
      () =>
        page.evaluate(async () => {
          const el = document.querySelector(".script-canvas") as HTMLElement;
          const top = el.scrollTop;
          for (let i = 1; i <= 40; i += 1) {
            el.scrollTop = top + i * 60;
            await new Promise((r) => requestAnimationFrame(r));
          }
        }),
      async () => undefined,
    );
    await page.evaluate(() => {
      (document.querySelector(".script-canvas") as HTMLElement).scrollTop = 0;
    });
    await frame(page);
  });
  await repeat(REPEATS, async () => {
    const line = page.locator(".line-card").nth(3);
    await measure(
      page,
      cdp,
      "focus-other-line@1000",
      () => line.locator(".line-text-editor").click(),
      () => expect(line.locator(".line-text-editor")).toBeFocused(),
    );
  });
});

// Continuous (infinite) CSS animations: cost of keeping them running for 2 s, summed from a Chromium trace.
const ANIMATION_CASES: Record<string, string> = {
  "idle (no animation)": "",
  "1 line is-generating": ".line-card:nth-of-type(1)|is-generating",
  "1 line is-playing": ".line-card:nth-of-type(1)|is-playing",
  "5 lines is-generating": ".line-card|is-generating|5",
  "auto-generate button is-generating": ".auto-generate-button|is-generating",
};

test("continuous animation cost", async ({ page, browser }) => {
  test.setTimeout(240_000);
  await boot(page, 60);
  for (const [name, spec] of Object.entries(ANIMATION_CASES)) {
    for (let i = 0; i < Math.min(REPEATS, 5); i += 1) {
      const [selector, className, count] = spec.split("|");
      await page.evaluate(
        ({ selector, className, count }) => {
          if (!selector) return;
          const nodes = Array.from(document.querySelectorAll(selector)).slice(0, Number(count ?? 1));
          for (const node of nodes) node.classList.add(className);
          (window as unknown as { __cls: Element[] }).__cls = nodes;
        },
        { selector, className, count },
      );
      await frame(page);
      await browser.startTracing(page, { categories: ["devtools.timeline", "disabled-by-default-devtools.timeline", "cc", "viz"] });
      await page.evaluate(() => (window as unknown as { __b: { start(): void } }).__b.start());
      await page.waitForTimeout(2000);
      const frames = await page.evaluate(() => {
        const b = (window as unknown as { __b: { frames: number[]; stop: boolean } }).__b;
        b.stop = true;
        return b.frames.slice(1);
      });
      const trace = JSON.parse((await browser.stopTracing()).toString()) as { traceEvents: { name: string; dur?: number; ph: string }[] };
      const sum = (names: string[]) => trace.traceEvents.filter((e) => names.includes(e.name) && e.ph === "X").reduce((a, e) => a + (e.dur ?? 0), 0) / 1000;
      await page.evaluate(
        ({ className }) => {
          for (const node of (window as unknown as { __cls?: Element[] }).__cls ?? []) node.classList.remove(className);
        },
        { className: className ?? "" },
      );
      (results["anim:" + name] ??= []).push({
        visibleMs: frames.reduce((a, f) => a + f, 0) / Math.max(1, frames.length),
        settleMs: 0,
        worstFrame: Math.max(0, ...frames),
        jank: frames.filter((f) => f > 25).length,
        scriptMs: sum(["FunctionCall", "EvaluateScript"]),
        layoutMs: sum(["Paint", "PrePaint", "Layerize"]),
        styleMs: sum(["RasterTask", "ImageDecodeTask"]),
        taskMs: sum(["UpdateLayoutTree", "Layout"]),
        longTasks: 0,
      });
    }
  }
});
