import { test } from "@playwright/test";
import { installMockApi } from "../e2e/mock-api";

// Settings page with registered TTS models: SHOT_DIR=<dir> pnpm exec playwright test -c playwright.bench.config.ts --grep "screens-tts"
test("screens-tts", async ({ page }) => {
  test.skip(!process.env.SHOT_DIR, "set SHOT_DIR to write screenshots");
  const dir = process.env.SHOT_DIR!;
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installMockApi(page, { registeredTts: true });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await page.getByRole("button", { name: "設定", exact: true }).click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: dir + "/tts-settings.png", animations: "disabled" });
  await page.locator(".model-selection-trigger").first().click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: dir + "/tts-popover.png", animations: "disabled" });
});
