import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installMockApi(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
});

test("script import dialog uses the shared form layout", async ({ page }) => {
  await page.locator(".project-menu").hover();
  await page.getByRole("button", { name: "台本読み込み" }).click();
  const dialog = page.locator(".script-import-modal");
  const source = dialog.getByLabel("台本データ");
  await expect(source).toBeFocused();
  await expect(page.locator(".notice-character:not(.is-settled)")).toHaveCount(0);
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  await expect(dialog).toHaveScreenshot("script-import-dialog.png", { animations: "disabled" });
  await source.fill("入力中の台本");
  await expect(source).toHaveValue("入力中の台本");
  await dialog.getByRole("button", { name: "キャンセル", exact: true }).click();
  await expect(dialog).toHaveCount(0);
});

test("keeps one visible cancel action while returning from local LLM selection", async ({ page }) => {
  await page.getByRole("button", { name: "設定", exact: true }).click();
  await page
    .locator(".settings-panel")
    .filter({ has: page.getByRole("heading", { name: "LLM設定", exact: true }) })
    .locator(".model-selection-trigger")
    .click();
  const add = page.getByRole("listbox", { name: "LLMモデルの候補" }).getByRole("button", { name: /SCENA内蔵LLMにモデルを追加/ });
  await add.click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: /Mac内のフォルダから選ぶ/ }).click();
  const cancel = dialog.getByRole("button", { name: "キャンセル", exact: true });
  await expect(cancel).toHaveCount(1);
  await expect(cancel).toBeVisible();
  await expect(cancel).toHaveCSS("opacity", "1");
  await expect(cancel).toHaveCSS("transition-duration", "0s");
  await expect(dialog.locator(".llm-route-footer.is-local")).toHaveCSS("position", "static");
  await dialog.getByRole("button", { name: "戻る", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "キャンセル", exact: true })).toHaveCount(1);
  await expect(dialog.locator(".llm-route-footer.is-start")).toHaveCSS("backdrop-filter", "none");
  await expect(dialog.getByRole("button", { name: "戻る", exact: true })).toHaveCount(0);
  await dialog.getByRole("button", { name: "キャンセル", exact: true }).click();
  await expect(dialog).toHaveCount(0);
});
