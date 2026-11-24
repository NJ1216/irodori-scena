import { test } from "@playwright/test";
import { installMockApi } from "../e2e/mock-api";

// "Add voice model" dialog with the first card expanded: SHOT_DIR=<dir> pnpm exec playwright test -c playwright.bench.config.ts --grep "screens-tts-dialog"
test("screens-tts-dialog", async ({ page }) => {
  test.skip(!process.env.SHOT_DIR, "set SHOT_DIR to write screenshots");
  const dir = process.env.SHOT_DIR!;
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installMockApi(page, { registeredTts: true });
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page.goto("/");
  await page.getByRole("button", { name: "設定", exact: true }).click();
  await page.locator(".model-selection-trigger").first().click();
  await page.getByRole("button", { name: /\+ 音声モデル/ }).click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: dir + "/add-dialog.png", animations: "disabled" });
  await page.locator(".tts-variant-toggle").first().click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: dir + "/add-dialog-expanded.png", animations: "disabled" });
});
