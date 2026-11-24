import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test.beforeEach(async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "プロジェクト" }).hover();
  await page.getByRole("button", { name: "台本読み込み" }).click();
});

test("imports an inherited speaker line as separate dialogue", async ({ page }) => {
  await page.getByLabel("台本データ").fill("佐倉:こんにちは。\n続きの台詞。\n水瀬|やあ。");
  await page.getByRole("button", { name: "台本に読み込む" }).click();

  await expect(page.getByRole("status")).toContainText("3行を台本に読み込みました");
  await expect(page.locator(".line-text-editor")).toHaveCount(5);
  await expect(page.locator(".line-text-editor").nth(3)).toHaveText("続きの台詞。");
});

test("requires a cast name on the first line when later lines name speakers", async ({ page }) => {
  await page.getByLabel("台本データ").fill("前置き\n佐倉:こんにちは。");

  await expect(page.getByRole("alert")).toContainText("最初の発話行にキャスト名を付けてください。");
  await expect(page.getByRole("button", { name: "台本に読み込む" })).toBeDisabled();
});

test("keeps the single-cast flow for scripts without speaker notation", async ({ page }) => {
  await page.getByLabel("台本データ").fill("一行目\n\n　二行目");
  await page.getByLabel("すべての台詞のキャスト").selectOption({ label: "佐倉 紗良" });
  await page.getByRole("button", { name: "台本に読み込む" }).click();

  await expect(page.getByRole("status")).toContainText("2行を台本に読み込みました");
  await expect(page.locator(".line-text-editor")).toHaveCount(4);
});
