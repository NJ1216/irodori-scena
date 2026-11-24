import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installMockApi(page);
});

test("range controls share the SCENA range primitive", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");

  const scriptRange = page.locator(".gap-control input[type=range]").first();
  await expect(scriptRange).toHaveClass(/range-control/);
  await expect(page.getByLabel("共通の話速（スライダー）")).toHaveClass(/range-control/);
  await expect(scriptRange).toHaveCSS("height", "18px");
  await scriptRange.focus();
  await expect(scriptRange).toBeFocused();
  await scriptRange.press("End");
  await scriptRange.click({ button: "right" });
  await expect(scriptRange).toHaveValue("1.2");
  await page.getByRole("button", { name: "AI台本" }).click();
  await page.locator(".draft-cast-picker-item").first().click();
  const draftRange = page.getByLabel("だいたいの総尺（分）");
  await expect(draftRange).toHaveClass(/range-control/);
  await expect(draftRange).toHaveCSS("height", "18px");
  await draftRange.focus();
  await expect(draftRange).toBeFocused();
  await draftRange.press("End");
  await draftRange.click({ button: "right" });
  await expect(draftRange).toHaveValue("3");
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await page.getByRole("button", { name: "設定を編集" }).first().click();
  await page.locator(".avatar-file-input").setInputFiles({
    name: "avatar.png",
    mimeType: "image/png",
    buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL7VwAAAABJRU5ErkJggg==", "base64"),
  });
  const avatarRange = page.locator(".avatar-crop-modal .range-control");
  await expect(avatarRange).toBeVisible();
  await expect(avatarRange).toHaveClass(/range-control/);
  await expect(avatarRange).toHaveCSS("height", "18px");
  await avatarRange.focus();
  await expect(avatarRange).toBeFocused();
  await avatarRange.press("End");
  await avatarRange.click({ button: "right" });
  await expect(avatarRange).toHaveValue("1");
  await page.locator(".avatar-crop-preview").hover();
  await page.mouse.wheel(0, -100);
  await expect(avatarRange).toHaveValue("1.1");
});

test("script quality presets keep the three CFG controls folded by default", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");

  const details = page.locator(".script-cfg-controls");
  await expect(details).not.toHaveAttribute("open", "");
  await expect(page.getByLabel("セリフへの追従（スライダー）")).not.toBeVisible();
  await page.getByLabel("CFG設定を開閉").click();

  const textCfg = page.getByText("textCfg", { exact: true });
  const textLabel = textCfg.locator("xpath=parent::i");
  const typography = await Promise.all([
    textCfg.evaluate((element) => ({
      size: parseFloat(getComputedStyle(element).fontSize),
      weight: getComputedStyle(element).fontWeight,
    })),
    textLabel.evaluate((element) => parseFloat(getComputedStyle(element).fontSize)),
  ]);
  expect(typography[0].size).toBeLessThan(typography[1]);
  expect(typography[0].weight).toBe("400");
  await expect(page.getByText("voiceCfg", { exact: true })).toBeVisible();
  await expect(page.getByText("captionCfg", { exact: true })).toBeVisible();

  const captionRange = page.getByLabel("声の指定への追従（スライダー）");
  await expect(captionRange).toHaveValue("3");
  await captionRange.focus();
  await captionRange.press("End");
  await expect(captionRange).toHaveValue("10");
});
