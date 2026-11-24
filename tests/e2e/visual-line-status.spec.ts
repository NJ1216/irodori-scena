import { expect, test, type Page } from "@playwright/test";
import { installMockApi } from "./mock-api";

async function finishNoticeAnimation(page: Page) {
  await expect(page.locator(".notice-character:not(.is-settled)")).toHaveCount(0);
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installMockApi(page);
});

test("project duration remains separate from the title at narrow widths", async ({ page }) => {
  await installMockApi(page, { generatedTake: true, completeTakes: true });

  for (const width of [1280, 600]) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/");
    const title = page.locator(".script-title-editor");
    await expect(title.getByLabel("総合時間 0分5秒")).toBeVisible();
    if (width === 1280) {
      await expect(title).toHaveScreenshot("script-title-duration.png", {
        animations: "disabled",
      });
    }
    await title.getByRole("button", { name: /SCRIPT TITLE/ }).click();
    await expect(title.getByLabel("総合時間 0分5秒")).toBeVisible();
    await page.getByLabel("台本タイトル").press("Escape");
    expect(
      await title.evaluate((element) => {
        const duration = element.querySelector(".script-title-duration");
        const titleText = element.querySelector(".script-title-display strong");
        if (!duration || !titleText) throw new Error("Title duration is missing");
        const durationRect = duration.getBoundingClientRect();
        const titleRect = titleText.getBoundingClientRect();
        return durationRect.top < titleRect.bottom && titleRect.right <= durationRect.left;
      }),
    ).toBe(true);
  }
});

test("generated line status fits its card", async ({ page }) => {
  await installMockApi(page, { generatedTake: true });

  for (const width of [1280, 600]) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/");

    const status = page.locator(".line-meta").first();
    await expect(status.locator(".line-status-icon")).toHaveCount(5);
    await expect(status.locator(".quality-pill")).toHaveText("バランス");
    await expect(status).not.toContainText("佐倉 紗良");
    await expect(status.locator(".line-result-status")).not.toContainText("テイク");
    if (width === 1280) {
      await expect(page.locator(".scene-box").first()).toHaveScreenshot("generated-line-status.png", {
        animations: "disabled",
      });
    }
    expect(await status.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    expect(
      await page
        .locator(".line-card")
        .first()
        .evaluate((element) => element.scrollWidth <= element.clientWidth),
    ).toBe(true);
    expect(
      await page
        .locator(".scene-box")
        .first()
        .evaluate((scene) => {
          const sceneRect = scene.getBoundingClientRect();
          return [...scene.querySelectorAll(".line-card")].every((line) => {
            const lineRect = line.getBoundingClientRect();
            return lineRect.left >= sceneRect.left && lineRect.right <= sceneRect.right && lineRect.top >= sceneRect.top && lineRect.bottom <= sceneRect.bottom;
          });
        }),
    ).toBe(true);
    const takeChoice = page.locator(".take-choice").first();
    await takeChoice.hover();
    const tooltip = takeChoice.locator(".take-tooltip");
    await expect(tooltip).toBeVisible();
    const layering = await tooltip.evaluate((element) => ({
      cardZIndex: getComputedStyle(element.closest(".line-card")!).zIndex,
      tooltipZIndex: getComputedStyle(element).zIndex,
      shadow: getComputedStyle(element).boxShadow,
    }));
    expect(Number(layering.cardZIndex)).toBeGreaterThan(0);
    expect(Number(layering.tooltipZIndex)).toBeGreaterThan(Number(layering.cardZIndex));
    expect(layering.shadow).not.toBe("none");
    await expect
      .poll(() =>
        tooltip.evaluate((element) => {
          const rect = element.getBoundingClientRect();
          const front = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
          return Boolean(front?.closest(".take-tooltip"));
        }),
      )
      .toBe(true);
    await expect(tooltip.locator(".line-status-icon")).toHaveCount(3);
    await expect(tooltip).toContainText("1681853295");
    await expect(tooltip).toContainText("1.00");
    await expect(tooltip.locator(".quality-pill")).toHaveText("バランス");
    await page.waitForTimeout(200);
    await tooltip.locator('.line-status-tooltip-anchor[title="Seed"]').hover();
    await expect(page.getByRole("tooltip", { name: "Seed", exact: true })).toBeVisible({ timeout: 500 });
    const saveTakeButton = tooltip.getByRole("button", { name: "このテイクのWAVを保存" });
    await expect(saveTakeButton).toBeVisible();
    await expect
      .poll(() =>
        saveTakeButton.evaluate((button) => {
          const rect = button.getBoundingClientRect();
          const icon = button.querySelector("svg")?.getBoundingClientRect();
          return rect.width === 23 && rect.height === 23 && icon?.width === 14 && icon?.height === 14;
        }),
      )
      .toBe(true);
    await expect
      .poll(() =>
        takeChoice.evaluate((element) => {
          const [takeButton, deleteButton] = element.querySelectorAll(":scope > button");
          if (!takeButton || !deleteButton) throw new Error("Take controls are missing");
          return takeButton.getBoundingClientRect().height === deleteButton.getBoundingClientRect().height;
        }),
      )
      .toBe(true);
    await expect(status.locator(".quality-pill")).toHaveClass(/quality-fast/);
  }
});

test("ungenerated line omits result status", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");

  const status = page.locator(".line-meta").first();
  await expect(status.locator(".line-result-status")).toHaveCount(0);
  await expect(status.locator(".quality-pill")).toHaveCount(0);
  await expect(status.locator(".line-status-icon")).toHaveCount(2);
  await expect(status).not.toContainText("佐倉 紗良");
  await expect(status).not.toContainText("テイク");
  await expect(status).not.toContainText("未生成");
});

test("empty line adjustments return to shared settings", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");

  const rate = page.getByLabel("発話行ごとの話速").first();
  const gap = page.getByLabel("発話行ごとの発話間隔（秒）").first();
  const disclosure = page.getByRole("button", { name: "行ごとのCFG設定を表示" }).first();
  await expect(disclosure).toHaveCSS("opacity", "0");
  await page.locator(".line-meta").first().hover();
  await expect(disclosure).toHaveCSS("opacity", "1");
  await disclosure.click();
  const textCfg = page.getByLabel("発話行ごとのtextCfg（台詞への追従）").first();
  const voiceCfg = page.getByLabel("発話行ごとのvoiceCfg（基準ボイスへの追従）").first();
  const captionCfg = page.getByLabel("発話行ごとのcaptionCfg（ト書きへの追従）").first();
  await expect(rate).not.toHaveClass(/is-shared/);
  await expect(gap).not.toHaveClass(/is-shared/);
  await expect(gap.locator("xpath=parent::span").locator("small")).toHaveText("秒");
  await expect(textCfg).toHaveAttribute("placeholder", "1.5");
  await expect(voiceCfg).toHaveAttribute("placeholder", "2.0");
  await expect(captionCfg).toHaveAttribute("placeholder", "3.0");
  await expect(textCfg).toHaveClass(/is-shared/);
  await rate.fill("");
  await gap.fill("");
  await gap.blur();
  await expect(rate).toHaveClass(/is-shared/);
  await expect(gap).toHaveClass(/is-shared/);
  await expect(rate).toHaveAttribute("placeholder", "1.00");
  await expect(gap).toHaveAttribute("placeholder", "0.7");
  await expect(page.locator(".line-meta").first()).not.toContainText("共通");

  await rate.fill("1.05");
  await gap.fill("0.6");
  await textCfg.fill("1.6");
  await voiceCfg.fill("12");
  await captionCfg.fill("4.4");
  await expect(rate).toHaveValue("1.05");
  await expect(gap).toHaveValue("0.6");
  await expect(textCfg).toHaveValue("1.6");
  await expect(voiceCfg).toHaveValue("12");
  await voiceCfg.blur();
  await expect(voiceCfg).toHaveAttribute("aria-invalid", "true");
  await expect(captionCfg).toHaveValue("4.4");
  await captionCfg.fill("");
  await captionCfg.blur();
  await expect(captionCfg).toHaveClass(/is-shared/);
});

test("negative gap remains user-controlled after commit", async ({ page }) => {
  await page.unroute("**/api/**");
  await installMockApi(page, { generatedTake: true, completeTakes: true });
  await page.goto("/");

  const gap = page.getByLabel("発話行ごとの発話間隔（秒）").first();
  await gap.fill("-4");
  await expect(gap).toHaveValue("-4");
  await gap.blur();
  await expect(gap).toHaveValue("-4");

  await gap.focus();
  await expect(gap).toHaveValue("-4");
  await gap.fill("-1");
  await gap.blur();
  await expect(gap).toHaveValue("-1");
});

test("voice modal and settings", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await page.getByRole("button", { name: /声をつくる/ }).click();
  await expect(page.getByRole("dialog", { name: "声の候補をつくる" })).toBeVisible();
  await finishNoticeAnimation(page);
  await expect(page).toHaveScreenshot("voice-modal.png", {
    animations: "disabled",
  });
  await page.getByRole("dialog", { name: "声の候補をつくる" }).getByRole("button", { name: "キャンセル" }).click();
  await page.getByRole("button", { name: "設定", exact: true }).click();
  await expect(page.getByRole("heading", { name: "設定", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "LAB設定", exact: true })).toBeVisible();
  await expect(page.locator(".settings-panels")).not.toContainText("確認中");
  await finishNoticeAnimation(page);
  await expect(page).toHaveScreenshot("settings.png", {
    animations: "disabled",
    fullPage: true,
  });
  await page.locator(".model-selection-trigger").nth(1).click();
  await expect(page).toHaveScreenshot("settings-models-expanded.png", {
    animations: "disabled",
    fullPage: true,
  });
  await page.getByRole("button", { name: "LLMモデルの詳細" }).click();
  await expect(page).toHaveScreenshot("llm-card-details.png", {
    animations: "disabled",
  });
});

test("voice design emoji palette fills the dialog in a 15 by 3 grid", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await page.getByRole("button", { name: /声をつくる/ }).click();

  const dialog = page.getByRole("dialog", { name: "声の候補をつくる" });
  await dialog.locator(".voice-sample-emoji-inserter > summary").click();
  const palette = dialog.locator(".voice-sample-emoji-inserter .emoji-palette");
  const buttons = palette.getByRole("button");
  await expect(buttons).toHaveCount(45);
  await expect(buttons.first()).toHaveCSS("text-indent", "0px");
  await expect(buttons.first()).toHaveCSS("padding", "0px");
  await expect(buttons.first().locator(".emoji-palette-glyph")).toHaveCSS("transform", "matrix(1, 0, 0, 1, -1, 0)");
  await expect.poll(() => palette.locator("> div").evaluate((element) => getComputedStyle(element).gridTemplateColumns.trim().split(/\s+/).length)).toBe(15);
  await expect.poll(() => buttons.evaluateAll((elements) => new Set(elements.map((element) => element.getBoundingClientRect().top)).size)).toBe(3);
  // The sticky action footer must not cover any row of the palette.
  await expect
    .poll(() =>
      buttons.evaluateAll((elements) =>
        elements.every((element) => {
          const bounds = element.getBoundingClientRect();
          const hit = document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
          return hit !== null && element.contains(hit);
        }),
      ),
    )
    .toBe(true);
  await expect(palette).toHaveScreenshot("voice-design-emoji-grid.png", {
    animations: "disabled",
  });
});

test("AI draft composer", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await page.getByRole("button", { name: "AI台本" }).click();
  await expect(page.getByRole("heading", { name: "AIに台本の下書きを頼む", exact: true })).toBeVisible();
  await finishNoticeAnimation(page);
  await expect(page).toHaveScreenshot("draft-composer.png", {
    animations: "disabled",
    fullPage: true,
  });
});
