import { expect, test, type Page } from "@playwright/test";
import { installMockApi } from "./mock-api";

test.beforeEach(async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");
  await expect(page.getByRole("button", { name: "SCRIPT TITLE 雨上がりの約束" })).toBeVisible();
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await page.getByRole("button", { name: /声をつくる/ }).click();
  await page.getByRole("button", { name: "基準ボイス候補をつくる" }).click();
});

const overlay = (page: Page) => page.getByRole("status", { name: "通知" });
const dialog = (page: Page) => page.getByRole("dialog", { name: "声の候補をつくる" });

test("shows a notice raised inside a dialog centered above a dimmed dialog until dismissed", async ({ page }) => {
  await expect(overlay(page)).toContainText("声の条件を1項目以上入力してください");
  const stack = await page.evaluate(() => {
    const notice = document.querySelector(".centered-notice");
    const dialogElement = document.querySelector('[role="dialog"]');
    if (!notice || !dialogElement) return null;
    const box = notice.getBoundingClientRect();
    const dialogBox = dialogElement.getBoundingClientRect();
    const atNotice = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    const atDialogCorner = document.elementFromPoint(dialogBox.left + 8, dialogBox.top + 8);
    return { noticeOnTop: notice.contains(atNotice), dialogDimmed: atDialogCorner?.classList.contains("notice-overlay-scrim") ?? false };
  });
  expect(stack).toEqual({ noticeOnTop: true, dialogDimmed: true });
  await expect(page.getByRole("button", { name: "通知を閉じる" })).toBeFocused();
  await page.waitForTimeout(3500);
  await expect(overlay(page)).toBeVisible();
});

test("closes the overlay with Escape while the dialog stays open", async ({ page }) => {
  await expect(overlay(page)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(overlay(page)).toBeHidden();
  await expect(dialog(page)).toBeVisible();
});

test("closes the overlay with its close button", async ({ page }) => {
  await page.getByRole("button", { name: "通知を閉じる" }).click();
  await expect(overlay(page)).toBeHidden();
  await expect(dialog(page)).toBeVisible();
});

test("closes the overlay when the dimmed area is clicked, keeping the dialog", async ({ page }) => {
  await expect(overlay(page)).toBeVisible();
  await page.mouse.click(12, 12);
  await expect(overlay(page)).toBeHidden();
  await expect(dialog(page)).toBeVisible();
});
