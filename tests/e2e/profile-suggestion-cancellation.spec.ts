import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test("keeps profile suggestion cancellation available while generating", async ({ page }) => {
  await installMockApi(page);
  await page.route("**/api/characters/profile-suggestion/jobs/profile-e2e/events", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 2_000));
    await route.fulfill({ status: 200, contentType: "text/event-stream", body: "" }).catch(() => undefined);
  });
  await page.goto("/");
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await page.getByRole("button", { name: "設定を編集" }).first().click();
  await page
    .locator(".character-edit-modal")
    .getByRole("button", { name: /AIに設定を作ってもらう/ })
    .click();
  await page.getByRole("button", { name: "設定を生成" }).click();

  const cancel = page.locator(".character-profile-suggestion-modal").getByRole("button", { name: "キャンセル" });
  await expect(cancel).toBeEnabled();
  await cancel.click();
  await expect(page.locator(".character-profile-suggestion-modal")).toHaveCount(0);
});
