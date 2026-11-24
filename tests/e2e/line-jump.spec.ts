import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test.beforeEach(async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");
  await expect(page.getByRole("button", { name: "SCRIPT TITLE 雨上がりの約束" })).toBeVisible();
});

test("shows line jump input and accepts Enter or a closing period", async ({ page }) => {
  await page.keyboard.type(".2");
  const jump = page.getByRole("status", { name: "発話行番号へ移動" });
  await expect(jump).toBeVisible();
  await expect(jump.getByLabel("移動先の発話行番号")).toHaveValue("2");
  await page.keyboard.press("Enter");
  await expect(jump).toBeHidden();
  await expect(page.locator('[data-line-id="line-2"]')).toHaveClass(/is-focused/);

  await page.keyboard.type(".1.");
  await expect(jump).toBeHidden();
  await expect(page.locator('[data-line-id="line-1"]')).toHaveClass(/is-focused/);
});

test("jumps to the first line of a scene by its case-insensitive label", async ({ page }) => {
  await page.keyboard.type(".2.");
  await expect(page.locator('[data-line-id="line-2"]')).toHaveClass(/is-focused/);

  await page.keyboard.type(".a");
  const jump = page.getByRole("status", { name: "シーン先頭へ移動" });
  await expect(jump).toBeVisible();
  await expect(jump.getByLabel("移動先のシーン記号")).toHaveValue("a");
  await page.keyboard.press("Enter");
  await expect(jump).toBeHidden();
  await expect(page.locator('[data-line-id="line-1"]')).toHaveClass(/is-focused/);

  await page.keyboard.type(".2..A.");
  await expect(page.locator('[data-line-id="line-1"]')).toHaveClass(/is-focused/);
});
