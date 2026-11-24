import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test.beforeEach(async ({ page }) => {
  await installMockApi(page, { generatedTake: true });
  await page.goto("/");
});

test("reveals line playback and deletion only while its line is active", async ({ page }) => {
  const card = page.locator('[data-line-id="line-1"]');
  const play = card.getByRole("button", { name: "1行を台本順に再生" });
  const remove = card.getByRole("button", { name: "この発話行を削除" });
  const transientActions = card.locator(".line-transient-actions");
  const idleHeight = await card.evaluate((element) => element.getBoundingClientRect().height);
  const generateLeft = await card.locator(".generate").evaluate((element) => element.getBoundingClientRect().left);

  await expect(play).not.toBeVisible();
  await expect(remove).not.toBeVisible();
  await expect(transientActions).toHaveCSS("width", "0px");
  await expect(transientActions).toHaveCSS("opacity", "0");
  await expect(transientActions).toHaveCSS("transition-property", "opacity");
  await expect(transientActions).toHaveCSS("transition-duration", "0.14s");

  await card.hover();
  await expect(play).toBeVisible();
  await expect(remove).toBeVisible();
  await expect(transientActions).toHaveCSS("width", "74px");
  await expect(card.locator(".line-play-toggle")).toHaveCSS("width", "34px");
  expect(await card.evaluate((element) => element.getBoundingClientRect().height)).toBe(idleHeight);
  expect(await card.locator(".generate").evaluate((element) => element.getBoundingClientRect().left)).toBe(generateLeft);

  await page.mouse.move(0, 0);
  await expect(play).not.toBeVisible();
  await expect(transientActions).toHaveCSS("width", "0px");
  await card.focus();
  await expect(play).toBeVisible();

  const ungeneratedCard = page.locator('[data-line-id="line-2"]');
  await ungeneratedCard.locator(".line-main").click();
  await expect(play).not.toBeVisible();
  await expect(ungeneratedCard.locator(".line-transient-actions")).toHaveCSS("width", "34px");
  await card.locator(".line-main").click();
  await expect(card).toHaveClass(/is-selected/);
  await expect(play).toBeVisible();
  await expect(remove).toBeVisible();
});
