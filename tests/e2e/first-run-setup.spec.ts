import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test("guides first-run setup and remembers explicit dismissal", async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 760 });
  await installMockApi(page, { firstRun: true });
  await page.goto("/");
  const dialog = page.getByRole("dialog", { name: "生成機能の準備" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Irodori-TTS v4.1 Small", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "推奨モデルをダウンロード" })).toBeVisible();
  await dialog.getByRole("button", { name: "LLM設定を開く" }).click();
  await expect(page.getByRole("heading", { name: "LLM設定" })).toBeFocused();
  await page.reload();
  await expect(dialog).toHaveCount(0);
});

test("keeps a TTS download running when the guide is dismissed", async ({ page }) => {
  await installMockApi(page, { firstRun: true, downloadsRunning: true });
  let cancelled = false;
  page.on("request", (request) => {
    if (request.url().endsWith("/cancel")) cancelled = true;
  });
  await page.goto("/");
  const dialog = page.getByRole("dialog", { name: "生成機能の準備" });
  await dialog.getByRole("button", { name: "推奨モデルをダウンロード" }).click();
  await expect(dialog.getByText("必要な資産を導入中")).toBeVisible();
  await dialog.getByRole("button", { name: "あとで" }).click();
  expect(cancelled).toBe(false);
});
