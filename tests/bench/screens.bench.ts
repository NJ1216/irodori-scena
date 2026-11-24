import { expect, test } from "@playwright/test";
import { installMockApi } from "../e2e/mock-api";

// Pixel-comparison helper for CSS refactors: SHOT_DIR=<dir> pnpm exec playwright test -c playwright.bench.config.ts --grep "screens"
test("screens", async ({ page }) => {
  test.skip(!process.env.SHOT_DIR, "set SHOT_DIR to write screenshots");
  const dir = process.env.SHOT_DIR!;
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installMockApi(page);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "SCRIPT TITLE 雨上がりの約束" })).toBeVisible();
  const shot = (name: string) => page.screenshot({ path: dir + "/" + name + ".png", animations: "disabled" });
  await shot("script");
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await page.waitForTimeout(400);
  await shot("cast");
  await page.getByRole("button", { name: "設定を編集" }).first().click();
  await page.waitForTimeout(400);
  await shot("cast-edit-dialog");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);
  for (const name of ["AI台本", "設定", "読み辞書", "辞書"]) {
    const button = page.getByRole("button", { name, exact: true });
    if (await button.count()) {
      await button.first().click();
      await page.waitForTimeout(400);
      await shot("page-" + name);
    }
  }
});
