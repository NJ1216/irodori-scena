import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test("starts the web editor and local API", async ({ page, request }) => {
  const health = await request.get("http://127.0.0.1:8788/api/health");
  expect(health.ok()).toBeTruthy();
  await expect(health.json()).resolves.toMatchObject({ ok: true });

  await installMockApi(page);
  await page.goto("/");
  await expect(page.locator("#root")).not.toBeEmpty();

  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await expect(page.getByRole("heading", { name: "物語の声を、ここに集める" })).toBeVisible();
  await page.getByRole("button", { name: /声をつくる/ }).click();
  await expect(page.getByRole("dialog", { name: "声の候補をつくる" })).toBeVisible();
  await page.getByRole("dialog", { name: "声の候補をつくる" }).getByRole("button", { name: "キャンセル" }).click();
});

test("opens the development style guide and its live token audit", async ({ page }) => {
  await page.goto("/style-guide");
  await expect(page.getByRole("heading", { name: "SCENA スタイルガイド" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "コンポーネント一覧" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "デザインの基礎" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "フォーム" })).toBeVisible();
  await expect(page.getByLabel("話者")).toHaveValue("aoi");
  await expect(page.getByLabel("話者")).toHaveCSS("border-radius", "16px");
  await expect(page.getByLabel("話し方")).toHaveCSS("border-radius", "16px");
  await expect(page.getByLabel("自動生成を有効にする")).toBeChecked();
  await expect(page.getByLabel("自動生成を有効にする")).toHaveCSS("appearance", "none");
  await expect(page.getByLabel("バランス")).toHaveCSS("border-radius", "50%");
  await expect(page.getByRole("heading", { name: "挿入コントロール" })).toBeVisible();
  const lineInsert = page.getByRole("button", { name: "＋ 発話行を挿入" });
  const sceneInsert = page.getByRole("button", { name: "＋ シーンを挿入" });
  await expect(lineInsert).toHaveCSS("border-radius", "999px");
  await expect(sceneInsert).toHaveCSS("border-radius", "999px");
  await expect(lineInsert).toHaveCSS("height", "32px");
  await expect(sceneInsert).toHaveCSS("height", "32px");
  await expect(lineInsert).toHaveCSS("background-color", await sceneInsert.evaluate((button) => getComputedStyle(button).backgroundColor));
  const aiInsert = page.getByRole("button", { name: "✦ AIに依頼" });
  await expect(aiInsert).toHaveCSS("height", "32px");
  await expect(aiInsert).toHaveCSS("background-color", "rgb(112, 168, 163)");
  await lineInsert.hover();
  await expect(lineInsert).toHaveCSS("background-color", "rgb(119, 114, 176)");
  await aiInsert.hover();
  await expect(aiInsert).toHaveCSS("background-color", "rgb(80, 135, 129)");
  await expect(page.getByRole("heading", { name: "トークン未使用のCSS値" })).toBeVisible();
  await expect(page.getByRole("table")).toBeVisible();
  await page.getByRole("button", { name: "アプリへ戻る" }).click();
  await expect(page.getByRole("heading", { name: "SCENA スタイルガイド" })).not.toBeVisible();
});

test("opens and closes the style guide on the Tauri-compatible route", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/?style-guide=");
  await expect(page.getByRole("heading", { name: "SCENA スタイルガイド" })).toBeVisible();
  await page.getByRole("button", { name: "アプリへ戻る" }).click();
  await expect(page).not.toHaveURL(/style-guide/);
  await expect(page.getByRole("button", { name: "キャスト", exact: true })).toBeVisible();
});

test("keeps the component catalog usable at the minimum window width", async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 760 });
  await page.goto("/?style-guide=");
  await expect(page.getByRole("navigation", { name: "コンポーネント一覧" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "カラー" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "文字" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "余白と角丸" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(600);
  const guide = page.getByRole("main", { name: "SCENA スタイルガイド" });
  await guide.evaluate((element) => element.scrollTo({ top: element.scrollHeight }));
  await expect(page.getByRole("heading", { name: "トークン未使用のCSS値" })).toBeInViewport();
  expect(await guide.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
});
