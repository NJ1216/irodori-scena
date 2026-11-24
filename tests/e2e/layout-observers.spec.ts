import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test("updates page geometry across widths without observer delivery errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await installMockApi(page);
  await page.goto("/");
  await expect(page.locator(".line-card").first()).toBeVisible();
  for (const width of [600, 1280, 900, 600]) {
    await page.setViewportSize({ width, height: 800 });
    await expect(page.locator(".line-card").first()).toBeVisible();
    await page.getByRole("button", { name: "設定", exact: true }).click();
    await expect(page.getByRole("heading", { name: "設定", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "台本", exact: true }).click();
    await expect(page.locator(".line-card").first()).toBeVisible();
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  }
  expect(errors).toEqual([]);
});
