import { expect, test, type Browser, type Page } from "@playwright/test";
import { installMockApi } from "./mock-api";

const platforms = [
  ["macos", "MacIntel"],
  ["windows", "Win32"],
] as const;
const motionPreferences = ["no-preference", "reduce"] as const;
const scaleFactors = [1, 1.25, 1.5, 2] as const;

async function renderingPage(browser: Browser, navigatorPlatform: string, reducedMotion: (typeof motionPreferences)[number], deviceScaleFactor: number) {
  const context = await browser.newContext({ deviceScaleFactor });
  await context.addInitScript((platform) => Object.defineProperty(navigator, "platform", { configurable: true, get: () => platform }), navigatorPlatform);
  const page = await context.newPage();
  await page.emulateMedia({ reducedMotion });
  await installMockApi(page);
  await page.goto("/");
  await expect(page.locator(".line-card").first()).toBeVisible();
  return { context, page };
}

async function addStateFixtures(page: Page) {
  await page.evaluate(() => {
    const host = document.createElement("div");
    host.setAttribute("data-rendering-contract", "");
    host.innerHTML = `
      <button class="is-confirming">確認</button>
      <span class="project-loading-mark">🌸</span>
      <div class="progress-bar"><i></i></div>
      <span class="draft-generation-dots">...</span>
      <div class="voice-candidate-choice is-generating"><button disabled><span>A</span><svg class="voice-candidate-generating-border" viewBox="0 0 28 28"><rect x="1" y="1" width="26" height="26" rx="5" /></svg></button></div>
    `;
    document.body.append(host);
  });
}

for (const deviceScaleFactor of scaleFactors) {
  test(`keeps product rendering independent of platform and motion at scale ${deviceScaleFactor}`, async ({ browser }) => {
    const baselines = new Map<string, Record<string, string>>();
    for (const [platform, navigatorPlatform] of platforms) {
      for (const reducedMotion of motionPreferences) {
        const { context, page } = await renderingPage(browser, navigatorPlatform, reducedMotion, deviceScaleFactor);
        try {
          await addStateFixtures(page);
          await page.locator(".line-card").first().click();
          const style = await page.evaluate(() => {
            const read = (selector: string) => getComputedStyle(document.querySelector(selector)!);
            const selected = read(".line-card.is-selected");
            const confirmation = read("[data-rendering-contract] .is-confirming");
            const loading = read("[data-rendering-contract] .project-loading-mark");
            const progress = read("[data-rendering-contract] .progress-bar i");
            const dots = read("[data-rendering-contract] .draft-generation-dots");
            const candidate = read("[data-rendering-contract] .voice-candidate-choice.is-generating > button");
            const border = read("[data-rendering-contract] .voice-candidate-generating-border");
            const borderRect = read("[data-rendering-contract] .voice-candidate-generating-border rect");
            return {
              platform: document.documentElement.dataset.platform ?? "",
              scale: String(devicePixelRatio),
              selectedBorder: selected.borderColor,
              selectedOutline: `${selected.outlineStyle} ${selected.outlineWidth} ${selected.outlineColor}`,
              confirmationAnimation: confirmation.animationName,
              loadingAnimation: loading.animationName,
              progressAnimation: progress.animationName,
              dotsAnimation: dots.animationName,
              candidateAnimation: candidate.animationName,
              borderAnimation: border.animationName,
              borderWidth: border.width,
              borderHeight: border.height,
              vectorEffect: borderRect.vectorEffect,
            };
          });
          expect(style.platform).toBe(platform);
          expect(Number(style.scale)).toBe(deviceScaleFactor);
          expect(style.selectedOutline).toBe("solid 1px rgb(0, 95, 204)");
          // Reduced motion deliberately stops the destructive-confirmation pulse (primitives.css); the state itself stays visible.
          expect(style.confirmationAnimation).toBe(reducedMotion === "reduce" ? "none" : "scena-confirmation-attention");
          expect(style.loadingAnimation).toBe("project-loading-pulse");
          expect(style.progressAnimation).toBe("scena-progress");
          expect(style.dotsAnimation).toBe("scena-ellipsis");
          expect(style.candidateAnimation).toBe("voice-candidate-generating");
          expect(style.borderAnimation).toBe("voice-candidate-border-flow");
          expect(style.borderWidth).toBe("28px");
          expect(style.borderHeight).toBe("28px");
          expect(style.vectorEffect).toBe("non-scaling-stroke");
          // The confirmation pulse is the one deliberate motion-dependent rule, asserted above per preference.
          const comparison = { ...style, platform: "", scale: "", confirmationAnimation: "" };
          const key = String(deviceScaleFactor);
          if (!baselines.has(key)) baselines.set(key, comparison);
          expect(comparison).toEqual(baselines.get(key));
        } finally {
          await context.close();
        }
      }
    }
  });
}
