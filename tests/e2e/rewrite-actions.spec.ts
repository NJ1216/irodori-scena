import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test.beforeEach(async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");
});

test("reveals the line-local rewrite action without reserving idle space", async ({ page }) => {
  const card = page.locator('[data-line-id="line-1"]');
  const slot = card.locator(".line-rewrite-action-slot");
  const action = slot.locator(".line-rewrite-action");
  const cardHeight = (await card.boundingBox())?.height;

  await page.mouse.move(0, 0);
  await expect(slot).toHaveCSS("width", "0px");
  await expect(action).toHaveCSS("transition-property", "opacity");
  await expect(action).toHaveCSS("transition-duration", "0.14s");
  await card.hover();
  await expect(slot).toHaveCSS("width", "82px");
  await expect(action).toHaveCSS("opacity", "1");
  expect((await card.boundingBox())?.height).toBe(cardHeight);

  await card.getByRole("textbox").focus();
  await page.mouse.move(0, 0);
  await expect(slot).toHaveCSS("width", "0px");
});

test("opens a range rewrite from either selected line without collapsing selection", async ({ page }) => {
  await page.locator('[data-line-id="line-1"]').click();
  await page.keyboard.press("Shift+ArrowDown");
  const selectedLines = page.locator(".line-card.is-selected");
  await expect(selectedLines).toHaveCount(2);
  await page.mouse.move(0, 0);
  await expect(selectedLines.getByRole("button", { name: "書き直す" })).toHaveCount(2);
  await expect(selectedLines.locator(".line-rewrite-action-slot.is-visible")).toHaveCount(2);

  await selectedLines.nth(1).hover();
  await selectedLines.nth(1).getByRole("button", { name: "書き直す" }).click();
  const dialog = page.getByRole("dialog", { name: "AIで台本を編集" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("radio", { name: "同じ内容の言い換え" })).toBeChecked();
  await expect(dialog.getByRole("combobox", { name: "生成目標" })).toHaveCount(0);
  await expect(page.locator(".line-card.is-selected")).toHaveCount(2);

  await dialog.getByRole("button", { name: "閉じる" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.locator(".line-card.is-selected")).toHaveCount(2);
});

test("selects line ranges with Shift-click and toggles lines with Option-click", async ({ page }) => {
  const first = page.locator('[data-line-id="line-1"]');
  const second = page.locator('[data-line-id="line-2"]');
  await first.click();
  await second.click({ modifiers: ["Shift"] });
  await expect(page.locator(".line-card.is-selected")).toHaveCount(2);

  await first.click();
  await second.click({ modifiers: ["Alt"] });
  await expect(page.locator(".line-card.is-selected")).toHaveCount(2);
  await first.click({ modifiers: ["Alt"] });
  await expect(first).not.toHaveClass(/is-selected/);
  await expect(second).toHaveClass(/is-selected/);
});

test("keeps script geometry and scroll position stable while pointer selection changes", async ({ page }) => {
  await page.unroute("**/api/**");
  await installMockApi(page, { lineCount: 12 });
  await page.goto("/");
  const canvas = page.locator(".script-canvas");
  const cards = page.locator(".line-card");
  const first = page.locator('[data-line-id="line-6"]');
  const second = page.locator('[data-line-id="line-7"]');
  await first.scrollIntoViewIfNeeded();
  await first.click();
  await page.mouse.move(0, 0);
  await page.waitForTimeout(300);
  const before = {
    scrollTop: await canvas.evaluate((element) => element.scrollTop),
    cardHeights: await cards.evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height)),
  };

  await second.click({ modifiers: ["Shift"] });
  await page.mouse.move(0, 0);
  await page.waitForTimeout(300);
  await expect.poll(() => cards.evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height))).toEqual(before.cardHeights);
  await expect.poll(() => canvas.evaluate((element) => element.scrollTop)).toBe(before.scrollTop);

  await first.click();
  await page.mouse.move(0, 0);
  await page.waitForTimeout(300);
  await expect.poll(() => cards.evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height))).toEqual(before.cardHeights);
  await expect.poll(() => canvas.evaluate((element) => element.scrollTop)).toBe(before.scrollTop);

  await second.click({ modifiers: ["Alt"] });
  await page.mouse.move(0, 0);
  await page.waitForTimeout(300);
  await expect.poll(() => cards.evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height))).toEqual(before.cardHeights);
  await expect.poll(() => canvas.evaluate((element) => element.scrollTop)).toBe(before.scrollTop);
});

test("uses the expanded range when the rewrite button was already visible before shift selection", async ({ page }) => {
  const firstCard = page.locator('[data-line-id="line-1"]');
  await firstCard.click();
  await firstCard.hover();
  const alreadyVisibleButton = firstCard.getByRole("button", { name: "書き直す" });
  await expect(alreadyVisibleButton).toBeVisible();

  await page.keyboard.press("Shift+ArrowDown");
  await expect(page.locator(".line-card.is-selected")).toHaveCount(2);
  await firstCard.locator(".line-rewrite-action-slot").evaluate((slot) => {
    slot.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await expect(page.locator(".line-card.is-selected")).toHaveCount(2);
  await alreadyVisibleButton.click();
  const dialog = page.getByRole("dialog", { name: "AIで台本を編集" });
  await expect(dialog).toBeVisible();
  await expect(page.locator(".line-card.is-selected")).toHaveCount(2);
  const requestPromise = page.waitForRequest("**/api/lines/assistant/jobs");
  await dialog.getByRole("button", { name: /提案を生成/ }).click();
  const request = await requestPromise;

  expect(request.postDataJSON().line_ids).toEqual(["line-1", "line-2"]);
});

test("places playback and deletion to the right of rewrite in the Take row", async ({ page }) => {
  const card = page.locator('[data-line-id="line-1"]');
  await card.locator(".generate").click();
  await card.hover();

  const take = card.getByRole("button", { name: "Take 1", exact: true });
  const rewrite = card.getByRole("button", { name: "書き直す" });
  const actions = card.locator(".line-transient-actions");
  const row = card.locator(".line-take-row");
  await expect(card.locator(".line-rewrite-action-slot")).toHaveCSS("width", "82px");
  await expect(actions).toHaveCSS("width", "74px");
  const [takeBox, rewriteBox, actionsBox, rowBox] = await Promise.all([take.boundingBox(), rewrite.boundingBox(), actions.boundingBox(), row.boundingBox()]);
  if (!takeBox || !rewriteBox || !actionsBox || !rowBox) throw new Error("Take row controls must have layout boxes");

  expect(rewriteBox.x).toBeGreaterThan(takeBox.x);
  expect(actionsBox.x).toBeGreaterThan(rewriteBox.x);
  expect(rewriteBox.y + rewriteBox.height / 2).toBe(takeBox.y + takeBox.height / 2);
  expect(Math.round(rowBox.x + rowBox.width - actionsBox.x - actionsBox.width)).toBe(11);
});

test("keeps the rewrite action right-aligned before the first Take is generated", async ({ page }) => {
  const card = page.locator('[data-line-id="line-1"]');
  await card.hover();

  const rewrite = card.getByRole("button", { name: "書き直す" });
  const actions = card.locator(".line-transient-actions");
  const row = card.locator(".line-take-row");
  await expect(card.locator(".take-picker")).toHaveCount(0);
  await expect(card.locator(".line-rewrite-action-slot")).toHaveCSS("width", "82px");
  const [rewriteBox, actionsBox, rowBox] = await Promise.all([rewrite.boundingBox(), actions.boundingBox(), row.boundingBox()]);
  if (!rewriteBox || !actionsBox || !rowBox) throw new Error("Rewrite action and Take row must have layout boxes");

  expect(actionsBox.x).toBeGreaterThan(rewriteBox.x);
  expect(Math.round(rowBox.x + rowBox.width - actionsBox.x - actionsBox.width)).toBe(11);
});

test("presents rewrite proposals as a readable before-and-after comparison", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.route("**/api/lines/assistant/jobs", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "assistant-e2e",
        operation: "paraphrase",
        status: "completed",
        phase: "completed",
        message: "提案を確認できます。",
        overallProgress: 100,
        proposalId: "proposal-e2e",
        sourceSignature: "signature-e2e",
        groups: [
          {
            id: "group-e2e",
            sceneId: "scene-1",
            sceneTitle: "駅前",
            atomic: false,
            contiguous: true,
            warnings: [],
            originalRows: [
              {
                id: "line-1",
                characterId: "cast-sara",
                characterName: "佐倉 紗良",
                text: "雨、やっと上がったね。",
                stageDirection: "空を見上げて、ほっとしたように",
                enabled: true,
                hasTakes: false,
              },
            ],
            rows: [
              {
                id: "row-e2e",
                originalLineId: "line-1",
                characterId: "cast-sara",
                characterName: "佐倉 紗良",
                text: "ようやく雨が止んだね。少し空が明るくなってきた。",
                stageDirection: "晴れ間を見つけ、安堵をにじませて",
                speechRate: 1.05,
                gapSeconds: 0.8,
              },
            ],
          },
        ],
      }),
    });
  });

  const card = page.locator('[data-line-id="line-1"]');
  await card.hover();
  await card.getByRole("button", { name: "書き直す" }).click();
  await page
    .getByRole("dialog", { name: "AIで台本を編集" })
    .getByRole("button", { name: /提案を生成/ })
    .click();

  const dialog = page.getByRole("dialog", { name: "AIで台本を編集" });
  await expect(dialog.getByText("書き直し前")).toBeVisible();
  await expect(dialog.getByText("提案", { exact: true })).toBeVisible();
  await expect(dialog.getByText("空を見上げて、ほっとしたように")).toBeVisible();
  await expect(dialog.locator(".script-assistant-speaker-avatar")).toHaveCount(2);
  await expect(dialog).toHaveScreenshot("rewrite-proposal-comparison.png", { animations: "disabled" });
});
