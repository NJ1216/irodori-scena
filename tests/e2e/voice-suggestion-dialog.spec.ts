import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installMockApi(page);
});

test("voice suggestion dialog keeps its form layout", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await page.getByRole("button", { name: /声をつくる/ }).click();
  await page.getByRole("button", { name: "AIに声の設計を相談" }).click();

  const dialog = page.locator(".voice-suggestion-modal");
  await expect(dialog.getByLabel("声のアイデア")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "キャンセル" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "声の設計を提案" })).toBeVisible();
  await expect(dialog).toHaveScreenshot("voice-suggestion-dialog.png", {
    animations: "disabled",
    maxDiffPixels: 100,
  });
});
