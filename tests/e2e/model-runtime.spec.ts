import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";
import { registryFixture } from "./mock-api-fixtures";

for (const width of [600, 1280]) {
  test(`model runtime details preserve geometry and expose preparation at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await installMockApi(page, { registeredTts: true });
    const local = {
      ...registryFixture.cards[0],
      id: "local",
      endpointId: "local-endpoint",
      modelId: "Gemma",
      source: "managed",
      displayName: "Gemma-very-long-model-name-".repeat(7),
      runtimeId: "scena-test",
      runtime: { state: "missing", runtimeId: "scena-test", recommended: true, version: "0.6.4", job: { id: "job", state: "preparing", message: "ライブラリを取得しています。", runtimeId: "scena-test" } },
    };
    await page.route("**/api/llm/registry", (route) => route.fulfill({ json: { ...registryFixture, defaultCardId: local.id, endpoints: [...registryFixture.endpoints, { id: "local-endpoint", provider: "scena-local", baseUrl: "http://local", displayName: "SCENA" }], cards: [...registryFixture.cards, local] } }));
    await page.route("**/api/llm/cards/local/runtime/cancel", (route) => route.fulfill({ json: { state: "cancelled" } }));
    await page.goto("/");
    await page.getByRole("button", { name: "設定", exact: true }).click();
    await expect(page.locator(".llm-model-data-section")).toContainText("動作確認中");
    const management = page.getByRole("button", { name: "oMLX管理" });
    const before = await management.boundingBox();
    await management.hover();
    expect(await management.boundingBox()).toEqual(before);
    await management.focus();
    expect(await management.boundingBox()).toEqual(before);
    await page.getByRole("button", { name: "LLMモデルの詳細" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("combobox", { name: "実行基盤", exact: true })).toBeDisabled();
    await expect(dialog.getByText("ライブラリを取得しています。")).toBeVisible();
    const cancel = dialog.getByRole("button", { name: "取消" });
    await cancel.scrollIntoViewIfNeeded();
    expect(await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`model-runtime-${width}.png`) });
    await cancel.click();
    await dialog.getByRole("button", { name: "閉じる", exact: true }).click();
    await management.click();
    const manager = page.getByRole("dialog", { name: "oMLX管理" });
    await expect(manager.getByRole("combobox")).toHaveCount(0);
    await expect(manager.getByText("SCENA動作確認版 · 0.6.4")).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`runtime-management-${width}.png`) });
  });
}

for (const width of [600, 1280]) {
  test(`runtime selection confirms downloads and returns to the previous version at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await installMockApi(page, { registeredTts: true });
    const local = { ...registryFixture.cards[0], id: "local", endpointId: "local-endpoint", modelId: "Gemma", source: "managed", runtimeId: "scena-test", displayName: "Gemma", runtime: { state: "ready", runtimeId: "scena-test", recommended: true, version: "0.6.4", job: null } };
    await page.route("**/api/llm/registry", (route) => route.fulfill({ json: { ...registryFixture, defaultCardId: local.id, endpoints: [{ id: "local-endpoint", provider: "scena-local", baseUrl: "http://local", displayName: "SCENA" }], cards: [local] } }));
    await page.goto("/");
    await page.getByRole("button", { name: "設定", exact: true }).click();
    await page.getByRole("button", { name: "LLMモデルの詳細" }).click();
    const selector = page.getByRole("combobox", { name: "実行基盤", exact: true });
    await expect(selector.getByRole("option", { name: "oMLX v0.6.3 · 公開版" })).toBeAttached();
    const identity = page.getByRole("region", { name: "モデルと接続" });
    await expect(identity.getByRole("combobox", { name: "実行基盤" })).toBeVisible();
    await expect(identity.getByRole("button", { name: "基本動作を確認" })).toBeVisible();
    await expect(page.locator(".llm-card-dialog-details > .llm-detail-section")).toHaveCount(1);
    await expect(identity.getByRole("button")).toHaveCount(1);
    await page.screenshot({ path: testInfo.outputPath(`simple-runtime-${width}.png`) });
    await selector.selectOption("release:v0.6.3");
    const confirmation = page.getByRole("dialog", { name: "oMLX v0.6.3を取得しますか？" });
    await expect(confirmation).toBeVisible();
    expect(await confirmation.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`runtime-confirmation-${width}.png`) });
    await confirmation.getByRole("button", { name: "キャンセル" }).click();
    await expect(selector).toHaveValue("scena-test");
  });
}
