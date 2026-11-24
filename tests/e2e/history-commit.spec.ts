import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test.beforeEach(async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");
});

test("commits stage directions and scene titles once after editing", async ({ page }) => {
  let projectSaveCount = 0;
  await page.route("**/api/**", async (route) => {
    if ((route.request().method() === "PUT" && new URL(route.request().url()).pathname === "/api/project") || (route.request().method() === "PATCH" && /\/api\/(lines\/[^/]+|project\/metadata)$/.test(new URL(route.request().url()).pathname))) projectSaveCount += 1;
    await route.fallback();
  });

  await page.locator(".direction-toggle").first().click();
  const direction = page.locator(".direction-input").first();
  await direction.fill("");
  await direction.pressSequentially("息を潜めて、相手をうかがう");
  expect(projectSaveCount).toBe(0);
  await direction.blur();
  await expect.poll(() => projectSaveCount).toBe(1);

  const sceneTitle = page.getByRole("textbox", { name: "シーンタイトル" }).first();
  await sceneTitle.fill("");
  await sceneTitle.pressSequentially("駅前広場");
  expect(projectSaveCount).toBe(1);
  await sceneTitle.blur();
  await expect.poll(() => projectSaveCount).toBe(2);
});
