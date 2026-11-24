import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

async function openSettings(page: Parameters<typeof installMockApi>[0]) {
  await page.goto("/");
  await page.getByRole("button", { name: "設定", exact: true }).click();
}

async function expectProgressInDialogFooter(page: Parameters<typeof installMockApi>[0], progressSelector: string) {
  const dialog = page.getByRole("dialog");
  const progress = dialog.locator(progressSelector);
  await expect(progress).toBeVisible();
  await expect(progress.locator("xpath=ancestor::footer[1]")).toHaveClass(/dialog-footer/);
  await expect(dialog.locator("footer.dialog-footer")).toHaveCSS("position", "sticky");
  await expect(page.locator("footer.main-window-footer").locator(progressSelector)).toHaveCount(0);
}

test.beforeEach(async ({ page }) => {
  await installMockApi(page, { downloadsRunning: true, runtimeDownloadRunning: true });
  await openSettings(page);
});

test("keeps Irodori-TTS download progress in the dialog footer", async ({ page }) => {
  await page.locator(".model-selection-trigger").first().click();
  await page.getByRole("button", { name: /\+ 音声モデル/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator(".tts-catalog-card").filter({ hasText: "Irodori-TTS v4.1 Small" }).filter({ hasNotText: "Anime" }).getByRole("button", { name: "追加", exact: true }).click();
  await expectProgressInDialogFooter(page, ".tts-install-progress");
});

test("keeps LLM download progress in the dialog footer", async ({ page }) => {
  await page.locator(".model-selection-trigger").nth(1).click();
  await page.getByRole("button", { name: /\+ SCENA内蔵LLMにモデルを追加/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Hugging Faceから探す" }).click();
  await dialog.getByRole("button", { name: "検索", exact: true }).click();
  await dialog.getByText("E2E Model", { exact: true }).click();
  await dialog.getByRole("button", { name: "取得して追加" }).click();
  await expectProgressInDialogFooter(page, ".hf-download-status");
});

test("runtime management keeps its shared closing footer during installation", async ({ page }) => {
  await page.getByRole("button", { name: "oMLX管理" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator("footer.dialog-footer")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "閉じる" })).toBeEnabled();
  await expect(dialog.getByRole("combobox")).toHaveCount(0);
});
