import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test("keeps multiple lines selected while stepping their speech gaps", async ({ page }) => {
  await installMockApi(page, { lineCount: 3 });
  await page.goto("/");
  await page.locator('[data-line-id="line-1"]').click();
  await page.keyboard.press("Shift+ArrowDown");
  const selected = page.locator(".line-card.is-selected");
  await expect(selected).toHaveCount(2);

  const gaps = page.getByLabel("発話行ごとの発話間隔（秒）");
  await gaps.nth(0).click();
  await expect(selected).toHaveCount(2);
  await page.keyboard.press("ArrowUp");
  await expect(selected).toHaveCount(2);
  await expect(gaps.nth(0)).toHaveValue("0.8");
  await expect(gaps.nth(1)).toHaveValue("1");

  await page.keyboard.press("ArrowDown");
  await expect(gaps.nth(0)).toHaveValue("0.7");
  await expect(gaps.nth(1)).toHaveValue("0.9");
});

test("steps speech rate and each CFG field across selected lines", async ({ page }) => {
  await installMockApi(page, { lineCount: 3 });
  await page.goto("/");
  await page.locator('[data-line-id="line-1"]').click();
  await page.keyboard.press("Shift+ArrowDown");
  const selected = page.locator(".line-card.is-selected");
  await expect(selected).toHaveCount(2);

  const speechRates = page.getByLabel("発話行ごとの話速");
  await speechRates.first().click();
  await page.keyboard.press("ArrowUp");
  await expect(selected).toHaveCount(2);
  await expect(speechRates.nth(0)).toHaveValue("1.05");
  await expect(speechRates.nth(1)).toHaveValue("1");

  await page.getByLabel("行ごとのCFG設定を表示").first().click();
  await expect(selected).toHaveCount(2);
  for (const [label, expected] of [
    ["発話行ごとのtextCfg（台詞への追従）", "1.6"],
    ["発話行ごとのvoiceCfg（基準ボイスへの追従）", "2.1"],
    ["発話行ごとのcaptionCfg（ト書きへの追従）", "3.1"],
  ] as const) {
    const inputs = page.getByLabel(label);
    await inputs.first().click();
    await page.keyboard.press("ArrowUp");
    await expect(selected).toHaveCount(2);
    await expect(inputs).toHaveCount(2);
    await expect(inputs.nth(0)).toHaveValue(expected);
    await expect(inputs.nth(1)).toHaveValue(expected);
  }
});
