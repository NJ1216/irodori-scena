import { expect, test, type Locator } from "@playwright/test";
import { installMockApi } from "./mock-api";

async function requiredBox(locator: Locator) {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  return box!;
}

test.beforeEach(async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");
});

test("project exports open in a three-row submenu on the right", async ({ page }) => {
  await expect(page.locator(".export-menu")).toHaveCount(0);
  await expect(page.getByLabel("WAV保存メニュー")).toHaveCount(0);
  await page.locator(".project-menu").hover();
  const exportMenu = page.locator(".project-export-menu");
  await exportMenu.hover();

  const submenu = exportMenu.getByRole("menu", { name: "エクスポートメニュー" });
  await expect(submenu).toBeVisible();
  await expect(submenu.getByRole("menuitem")).toHaveCount(3);
  await expect(submenu.getByRole("menuitem")).toHaveText(["音声・字幕・台本", "プロジェクト", "キャスト"]);
  await expect(submenu).toHaveCSS("grid-template-columns", "144px");
  await expect(page.getByRole("dialog", { name: "プロジェクトの保存と読み込み" })).toHaveCount(0);
  await expect(page.locator('input[accept*="zip"]')).toHaveCount(0);
  expect(await submenu.evaluate((menu) => menu.scrollWidth <= menu.clientWidth)).toBe(true);
  for (const item of await submenu.getByRole("menuitem").all()) {
    expect(await item.evaluate((button) => button.scrollWidth <= button.clientWidth && button.scrollHeight <= button.clientHeight)).toBe(true);
  }
  const trigger = exportMenu.locator(".project-export-trigger");
  const label = trigger.locator(".project-menu-label");
  const arrow = trigger.locator('span[aria-hidden="true"]');
  const [parentBox, submenuBox, triggerBox, labelBox, arrowBox] = await Promise.all([requiredBox(exportMenu), requiredBox(submenu), requiredBox(trigger), requiredBox(label), requiredBox(arrow)]);
  expect(submenuBox.x).toBeGreaterThan(parentBox.x);
  expect(Math.abs(labelBox.x + labelBox.width / 2 - (triggerBox.x + triggerBox.width / 2))).toBeLessThanOrEqual(1);
  expect(Math.round(triggerBox.x + triggerBox.width - (arrowBox.x + arrowBox.width))).toBe(10);

  await expect(exportMenu.getByRole("button", { name: /エクスポート/ })).toHaveAttribute("aria-haspopup", "menu");
  await submenu.getByRole("menuitem", { name: "音声・字幕・台本", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "エクスポート", exact: true })).toBeVisible();
  await page.getByLabel("発話行ごとに分割").check();
  await expect(page.getByLabel("命名要素1")).toHaveValue("sequence");
  await expect(page.getByLabel("命名要素2")).toHaveValue("cast");
  await expect(page.getByLabel("命名要素3")).toHaveValue("text");
  await expect(page.getByText("字幕TXT（開発版）")).toHaveCount(0);
  await page.getByLabel("字幕TXT").check();
  await expect(page.getByText("字幕TXT（開発版）")).toBeVisible();
  await expect(page.getByLabel("絵文字を含む発話行をそのまま出力する")).not.toBeChecked();

  await page.getByRole("button", { name: "キャンセル" }).click();
  await page.locator(".project-menu").hover();
  await exportMenu.hover();
  await submenu.getByRole("menuitem", { name: "プロジェクト", exact: true }).click();
  await expect(page.getByText(/プロジェクトをバックアップできませんでした: .*デスクトップアプリ専用/)).toBeVisible();
  await page.locator(".project-menu").hover();
  await exportMenu.hover();
  await submenu.getByRole("menuitem", { name: "キャスト", exact: true }).click();
  const castDialog = page.getByRole("dialog", { name: "キャストエクスポート" });
  await expect(castDialog).toBeVisible();
  await expect(castDialog.getByRole("button", { name: "エクスポート", exact: true })).toBeDisabled();
});
