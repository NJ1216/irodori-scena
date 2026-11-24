import { expect, test } from "@playwright/test";
import { testToneWav } from "./audio-fixtures";
import { installMockApi } from "./mock-api";

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installMockApi(page);
});

test("drags a dialogue card background to a new cue boundary", async ({ page }) => {
  await page.goto("/");
  const cards = page.locator(".script-canvas .line-card");
  await expect(cards).toHaveCount(2);
  const originalIds = await cards.evaluateAll((items) => items.map((item) => (item as HTMLElement).dataset.lineId));
  const source = await cards.first().boundingBox();
  const destination = await cards.last().boundingBox();
  expect(source).not.toBeNull();
  expect(destination).not.toBeNull();
  await page.mouse.move(source!.x + 3, source!.y + source!.height / 2);
  await page.mouse.down();
  expect(await page.evaluate(() => window.getSelection()?.toString())).toBe("");
  await page.mouse.move(source!.x + 12, source!.y + source!.height / 2 + 8);
  expect(await page.evaluate(() => window.getSelection()?.toString())).toBe("");
  await expect(page.locator(".line-drag-ghost")).toBeVisible();
  await expect(page.locator(".line-drag-ghost [data-drag-ghost-card='true']")).toBeVisible();
  await expect(page.locator(".line-drag-ghost [data-drag-ghost-card='true']")).toHaveCount(1);
  await expect(page.locator(".line-drag-ghost")).toContainText("雨、やっと上がったね。");
  await page.mouse.move(destination!.x + destination!.width / 2, destination!.y + destination!.height / 2, { steps: 4 });
  expect(await page.evaluate(() => window.getSelection()?.toString())).toBe("");
  await expect(cards.last().locator(".line-text-editor")).toHaveCSS("pointer-events", "none");
  await page.mouse.move(destination!.x + destination!.width / 2, destination!.y + destination!.height - 2);
  const dropTarget = page.locator(".line-insert-zone.is-line-drop-target");
  await expect(dropTarget).toBeVisible();
  expect(await page.evaluate(() => window.getSelection()?.toString())).toBe("");
  await page.mouse.up();
  await expect.poll(() => cards.evaluateAll((items) => items.map((item) => (item as HTMLElement).dataset.lineId))).toEqual([...originalIds.slice(1), originalIds[0]]);
  await expect(page.locator(".line-drag-ghost")).toHaveCount(0);
  await cards.first().locator(".line-main").click();
  await expect(cards.first()).toHaveClass(/is-selected/);
  await expect(page.locator(".line-card.is-selected")).toHaveCount(1);
});

test("stacks up to five empty cards behind a multi-line drag", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1600 });
  await page.unroute("**/api/**");
  await installMockApi(page, { lineCount: 7 });
  await page.goto("/");
  const cards = page.locator(".script-canvas .line-card");
  await expect(cards).toHaveCount(7);
  const originalIds = await cards.evaluateAll((items) => items.map((item) => (item as HTMLElement).dataset.lineId));

  const startDrag = async (selectionCount: number, grabbedIndex = selectionCount - 1) => {
    await cards.first().locator(".line-main").click();
    await cards
      .nth(selectionCount - 1)
      .locator(".line-main")
      .click({ modifiers: ["Shift"] });
    await expect(page.locator(".line-card.is-selected")).toHaveCount(selectionCount);
    const bounds = await cards.nth(grabbedIndex).boundingBox();
    expect(bounds).not.toBeNull();
    await page.mouse.move(bounds!.x + 3, bounds!.y + bounds!.height / 2);
    await page.mouse.down();
    await page.mouse.move(bounds!.x + 12, bounds!.y + bounds!.height / 2 + 8);
    await expect(page.locator(".line-drag-ghost")).toBeVisible();
  };

  await startDrag(2, 1);
  await expect(page.locator(".line-card.is-selected")).toHaveCount(2);
  await expect(page.locator(".line-card.is-selected").first()).toHaveCSS("opacity", "0.38");
  await expect(page.locator(".line-card.is-selected").last()).toHaveCSS("opacity", "0.38");
  await expect(page.locator(".line-drag-ghost [data-drag-ghost-card='true']")).toHaveCount(2);
  await expect(page.locator(".line-drag-ghost")).toContainText("雨、やっと上がったね。");
  await page.keyboard.press("Escape");
  await page.mouse.up();

  await startDrag(5);
  await expect(page.locator(".line-drag-ghost [data-drag-ghost-card='true']")).toHaveCount(5);
  await page.keyboard.press("Escape");
  await page.mouse.up();

  await startDrag(6);
  const ghostCards = page.locator(".line-drag-ghost [data-drag-ghost-card='true']");
  await expect(ghostCards).toHaveCount(5);
  await expect(page.locator(".line-drag-ghost")).not.toContainText(/\d+行/);
  const offsets = await page.locator(".line-drag-ghost-silhouette").evaluateAll((items) => {
    const front = document.querySelector(".line-drag-ghost-preview")!.getBoundingClientRect();
    return items.map((item) => {
      const bounds = item.getBoundingClientRect();
      return { x: Math.round(bounds.left - front.left), y: Math.round(bounds.top - front.top) };
    });
  });
  expect(offsets).toEqual([
    { x: 15, y: 15 },
    { x: 12, y: 12 },
    { x: 8, y: 8 },
    { x: 4, y: 4 },
  ]);

  const destination = await cards.last().boundingBox();
  expect(destination).not.toBeNull();
  await page.mouse.move(destination!.x + destination!.width / 2, destination!.y + destination!.height / 2, { steps: 4 });
  await page.mouse.move(destination!.x + destination!.width / 2, destination!.y + destination!.height - 2, { steps: 4 });
  await expect(page.locator(".line-insert-zone.is-line-drop-target")).toBeVisible();
  await page.mouse.up();
  await expect.poll(() => cards.evaluateAll((items) => items.map((item) => (item as HTMLElement).dataset.lineId))).toEqual([originalIds[6], ...originalIds.slice(0, 6)]);
});

test("keeps generated metadata selectable instead of starting a line drag", async ({ page }) => {
  await page.unroute("**/api/**");
  await installMockApi(page, { generatedTake: true });
  await page.goto("/");
  const card = page.locator(".line-card").first();
  const seed = card.getByLabel("Seed 1681853295").locator(".line-seed-value");
  await expect(card).toHaveCSS("cursor", "pointer");
  await expect(seed).toHaveCSS("cursor", "text");
  const bounds = await seed.boundingBox();
  expect(bounds).not.toBeNull();
  await page.mouse.move(bounds!.x + 2, bounds!.y + bounds!.height / 2);
  await page.mouse.down();
  await page.mouse.move(bounds!.x + bounds!.width - 2, bounds!.y + bounds!.height / 2, { steps: 4 });
  await expect(page.locator(".line-drag-ghost")).toHaveCount(0);
  expect(await page.evaluate(() => window.getSelection()?.toString())).toContain("1681853295");
  await page.mouse.up();
});

test("opens the line seed menu below the dice and keeps it operable above following rows", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 700 });
  await page.unroute("**/api/**");
  await installMockApi(page, { generatedTake: true });
  await page.goto("/");
  const cards = page.locator(".line-card");
  await cards.first().locator(".line-main").click();
  await cards
    .last()
    .locator(".line-main")
    .click({ modifiers: ["Shift"] });
  await expect(page.locator(".line-card.is-selected")).toHaveCount(2);

  const trigger = cards.first().getByRole("button", { name: "Seed 1681853295" });
  await trigger.hover();
  const menu = page.getByRole("menu", { name: "Seed操作" });
  await expect(menu).toBeVisible();
  const triggerBox = await trigger.boundingBox();
  const menuBox = await menu.boundingBox();
  expect(triggerBox).not.toBeNull();
  expect(menuBox).not.toBeNull();
  expect(menuBox!.y).toBeGreaterThanOrEqual(triggerBox!.y + triggerBox!.height - 1);
  const hitTarget = await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.closest("[role='menu']")?.getAttribute("aria-label"), {
    x: menuBox!.x + menuBox!.width / 2,
    y: menuBox!.y + menuBox!.height - 3,
  });
  expect(hitTarget).toBe("Seed操作");

  await menu.getByRole("menuitem", { name: "seed値を固定" }).click();
  await expect(page.locator(".line-card.is-selected")).toHaveCount(2);
  const fixed = cards.first().getByRole("button", { name: "Seed 1681853295 固定中" });
  await expect(fixed).toHaveCSS("font-size", "11px");
  await expect(fixed).toHaveCSS("font-weight", "800");
  await expect(fixed).toHaveCSS("font-style", "italic");
  await expect(fixed.locator(".line-seed-value")).toHaveCSS("font-synthesis", "style");
  const presetDetailColor = await page
    .locator(".preset-card .preset-options small")
    .first()
    .evaluate((element) => getComputedStyle(element).color);
  await expect(fixed).toHaveCSS("color", presetDetailColor);
  await expect(fixed.locator(".line-fixed-seed-icon rect")).toHaveCSS("stroke", presetDetailColor);
  await expect(fixed.locator(".line-fixed-seed-icon rect")).toHaveCSS("fill", "none");
  await expect(fixed.locator(".line-fixed-seed-icon circle")).toHaveCSS("fill", "rgb(183, 92, 120)");
  await expect(fixed.locator(".line-fixed-seed-icon circle")).toHaveCount(1);
  await fixed.hover();
  await expect(page.getByRole("menuitem", { name: "seed値の固定を解除" })).toBeVisible();
  await page.getByRole("menuitem", { name: "seed値でtakeを追加" }).click();
  const editor = page.locator(".line-seed-editor");
  const seedInput = editor.getByRole("textbox", { name: "Seed値" });
  await expect(seedInput).toHaveValue("1681853295");
  const editorBox = await editor.boundingBox();
  expect(editorBox).not.toBeNull();
  expect(Math.abs(editorBox!.x - triggerBox!.x)).toBeLessThan(20);
  await seedInput.fill("321");
  await editor.getByRole("button", { name: "takeを追加" }).click();
  await expect(cards.first().getByRole("button", { name: "Seed 321 固定中" })).toBeVisible();
  await expect(cards.first().getByRole("button", { name: "Take 2", exact: true })).toHaveClass(/selected/);

  await cards.first().getByRole("button", { name: "Seed 321 固定中" }).hover();
  await page.getByRole("menuitem", { name: "seed値でtakeを追加" }).click();
  await expect(page.getByRole("textbox", { name: "Seed値" })).toHaveValue("321");
  await page.getByRole("textbox", { name: "Seed値" }).fill("654");
  await page.getByRole("button", { name: "takeを追加" }).click();
  await expect(cards.first().getByRole("button", { name: "Take 3", exact: true })).toHaveClass(/selected/);
  await cards.first().getByRole("button", { name: "Seed 654 固定中" }).hover();
  await page.getByRole("menuitem", { name: "seed値の固定を解除" }).click();
  await expect(cards.first().getByRole("button", { name: "Seed 654" })).toBeVisible();
});

test("narrow script scroll layout", async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 800 });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "SCRIPT TITLE 雨上がりの約束" })).toBeVisible();
  await expect(page).toHaveScreenshot("script-narrow.png", {
    animations: "disabled",
    fullPage: true,
  });
});

test("simultaneous cue is connected and keeps shared controls on its edges", async ({ page }) => {
  await page.unroute("**/api/**");
  await installMockApi(page, { simultaneousCue: true });
  await page.goto("/");
  const cards = page.locator(".line-card.is-cue-member");
  await expect(cards).toHaveCount(2);
  await expect(cards.nth(0).getByRole("button", { name: "同時キャストを追加" })).toHaveCount(1);
  await expect(cards.nth(0).locator(".cue-member-add svg")).toHaveCount(1);
  const triggerCenterOffset = await cards
    .nth(0)
    .locator(".cue-member-trigger")
    .evaluate((button) => {
      const icon = button.querySelector("svg")?.getBoundingClientRect();
      const bounds = button.getBoundingClientRect();
      return icon ? { x: Math.abs(icon.left + icon.width / 2 - (bounds.left + bounds.width / 2)), y: Math.abs(icon.top + icon.height / 2 - (bounds.top + bounds.height / 2)) } : null;
    });
  expect(triggerCenterOffset?.x).toBeLessThan(0.5);
  expect(triggerCenterOffset?.y).toBeLessThan(0.5);
  await cards.nth(0).getByRole("button", { name: "同時キャストを追加" }).hover();
  await expect(page.getByRole("tooltip", { name: "同時キャストを追加" })).toBeVisible({ timeout: 300 });
  await expect(cards.nth(1).locator(".line-number")).toHaveCount(0);
  await expect(cards.nth(0).getByLabel("発話行ごとの発話間隔（秒）")).toHaveCount(0);
  await expect(cards.nth(1).getByLabel("発話行ごとの発話間隔（秒）")).toHaveCount(0);
  await expect(cards.nth(0).locator(".line-cfg-controls")).toHaveCount(1);
  await expect(cards.nth(1).locator(".line-cfg-controls")).toHaveCount(1);
  const distance = await cards.evaluateAll(([head, tail]) => tail.getBoundingClientRect().top - head.getBoundingClientRect().bottom);
  expect(distance).toBeLessThanOrEqual(0);
  await cards.nth(0).locator(".line-main").click();
  await expect(page.locator(".line-card.is-cue-member.is-selected")).toHaveCount(2);
  await page.mouse.move(0, 0);
  await expect(cards.locator(".line-rewrite-action")).toHaveCount(2);
  await expect(cards.getByRole("button", { name: "書き直す" })).toHaveCount(2);
  await cards.nth(1).hover();
  await cards.nth(1).getByRole("button", { name: "書き直す" }).click();
  const rewriteDialog = page.getByRole("dialog", { name: "AIで台本を編集" });
  await expect(rewriteDialog.getByRole("radio", { name: "同じ内容の言い換え" })).toBeChecked();
  await expect(rewriteDialog.getByRole("combobox", { name: "生成目標" })).toHaveCount(0);
  await expect(page.locator(".line-card.is-cue-member.is-selected")).toHaveCount(2);
  await rewriteDialog.getByRole("button", { name: "閉じる" }).click();
  await cards.nth(0).locator(".line-main").click();
  await expect(cards.nth(0)).toHaveClass(/is-selected/);
  await expect(cards.nth(1)).not.toHaveClass(/is-selected/);
  const upperFocus = await cards.nth(0).evaluate((head) => ({ outline: getComputedStyle(head).outlineStyle, zIndex: getComputedStyle(head).zIndex }));
  expect(upperFocus.outline).not.toBe("none");
  expect(upperFocus.zIndex).toBe("2");
  const editor = cards.nth(1).getByRole("textbox");
  await editor.fill("追加入力");
  await expect(editor).toHaveText("追加入力");
});

test("adds a simultaneous cast from an avatar menu", async ({ page }) => {
  await page.unroute("**/api/**");
  await installMockApi(page, { simultaneousCue: true });
  await page.goto("/");
  const trigger = page.locator(".line-card.is-cue-head").getByRole("button", { name: "同時キャストを追加" });
  await trigger.click();
  const menu = page.getByRole("listbox", { name: "追加する同時キャスト" });
  const option = menu.getByRole("option", { name: "三人目" });
  await expect(option.locator(".cast-picker-option-avatar img")).toHaveCount(1);
  expect(
    await menu.evaluate((element) => {
      const bounds = element.getBoundingClientRect();
      return document.elementFromPoint(bounds.left + bounds.width / 2, bounds.bottom - 4)?.closest(".cast-picker-menu") === element;
    }),
  ).toBe(true);
  await expect(menu).toHaveCount(0, { timeout: 4_500 });
  await trigger.click();
  await option.click();
  await expect(page.locator(".line-card.is-cue-member")).toHaveCount(3);
  await expect(menu).toHaveCount(0);
});

test("line cast picker stays above following dialogue rows", async ({ page }) => {
  await page.goto("/");
  const firstLine = page.locator(".line-card").first();
  await firstLine.getByRole("button", { name: /キャストを選択：/ }).click();
  const menu = page.getByRole("listbox", { name: "キャストを選択" });
  await expect(menu).toBeVisible();
  expect(
    await menu.evaluate((element) => {
      const bounds = element.getBoundingClientRect();
      return document.elementFromPoint(bounds.left + bounds.width / 2, bounds.bottom - 4)?.closest(".cast-picker-menu") === element;
    }),
  ).toBe(true);
});

test("editing a simultaneous cue does not reflow the script scroller", async ({ page }) => {
  await page.unroute("**/api/**");
  await installMockApi(page, { simultaneousCue: true, lineCount: 12 });
  await page.goto("/");
  const canvas = page.locator(".script-canvas");
  const cards = page.locator(".line-card");
  const cueEditor = page.locator(".line-card.is-cue-member").first().getByRole("textbox");
  const before = {
    scrollTop: await canvas.evaluate((element) => element.scrollTop),
    cardHeights: await cards.evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height)),
  };
  await cueEditor.click();
  await page.mouse.move(0, 0);
  await page.waitForTimeout(300);
  await expect.poll(() => cards.evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height))).toEqual(before.cardHeights);
  await expect.poll(() => canvas.evaluate((element) => element.scrollTop)).toBe(before.scrollTop);
  await page.locator(".line-card.is-cue-member").nth(1).locator(".line-main").click();
  await page.mouse.move(0, 0);
  await page.waitForTimeout(300);
  await expect.poll(() => cards.evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height))).toEqual(before.cardHeights);
  await expect.poll(() => canvas.evaluate((element) => element.scrollTop)).toBe(before.scrollTop);
});

test("enter moves text input to the next line and the final line hides its gap", async ({ page }) => {
  await page.goto("/");
  const cards = page.locator(".line-card");
  const editor = cards.first().getByRole("textbox");

  await expect(cards.first().getByLabel("発話行ごとの発話間隔（秒）")).toHaveCount(1);
  await expect(cards.last().getByLabel("発話行ごとの発話間隔（秒）")).toHaveCount(0);
  await expect(cards.last().locator(".line-cfg-controls")).toHaveCount(1);

  await editor.click();
  await editor.press("End");
  await editor.press("Shift+Enter");
  await editor.pressSequentially("二行目");
  await expect.poll(() => editor.evaluate((element) => element.innerText)).toBe("雨、やっと上がったね。\n二行目");
});

test("simultaneous cast switches between linked rate and fixed seconds", async ({ page }) => {
  await page.unroute("**/api/**");
  await installMockApi(page, { simultaneousCue: true, generatedTake: true });
  await page.goto("/");
  const tail = page.locator(".line-card.is-cue-member").nth(1);
  await expect(tail.getByLabel("発話行ごとの話速")).toHaveValue("0.95");
  const toggle = tail.getByRole("button", { name: "話速と秒指定を切り替え" });
  await toggle.click();
  const duration = tail.getByLabel("生成時の秒数");
  await expect(duration).toHaveValue("5");
  const controlGap = await Promise.all([toggle.boundingBox(), duration.boundingBox()]);
  expect(controlGap[1]!.x - (controlGap[0]!.x + controlGap[0]!.width)).toBeLessThanOrEqual(4);
  await expect(toggle).toHaveClass(/is-seconds/);
  const secondsStyle = await toggle.evaluate((element) => ({
    backgroundColor: getComputedStyle(element).backgroundColor,
    stroke: getComputedStyle(element.querySelector("svg")!).stroke,
  }));
  expect(secondsStyle.backgroundColor).toBe("rgba(0, 0, 0, 0)");
  expect(secondsStyle.stroke).toBe("rgb(57, 125, 115)");
  await expect(tail.getByLabel("発話行ごとの話速")).toHaveCount(0);
  await toggle.click();
  await expect(tail.getByLabel("発話行ごとの話速")).toHaveValue("0.95");
});

test("regular line switches between rate and fixed seconds", async ({ page }) => {
  await page.goto("/");
  const line = page.locator(".line-card").first();
  await expect(line.getByLabel("発話行ごとの話速")).toHaveValue("1");
  await line.getByRole("button", { name: "話速と秒指定を切り替え" }).click();
  const duration = line.getByLabel("生成時の秒数");
  await expect(duration).toHaveValue("5");
  await expect(duration.locator("xpath=parent::span").locator("small")).toHaveText("秒");
  await expect(line.getByLabel("発話行ごとの話速")).toHaveCount(0);
});

test("continuous playback renders a simultaneous cue as one mix", async ({ page }) => {
  await page.unroute("**/api/**");
  // Long takes keep both cue members audibly active far longer than UI sampling can lag behind the audio clock under parallel load.
  await installMockApi(page, { simultaneousCue: true, generatedTake: true, completeTakes: true, takeDurationSeconds: 30 });
  const played: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.endsWith(".wav")) played.push(path);
  });
  await page.route("**/api/media/cue-mix.wav", (route) => route.fulfill({ body: testToneWav(5), contentType: "audio/wav" }));
  await page.goto("/");
  await page.getByRole("button", { name: "▶ 連続再生" }).click();
  await expect.poll(() => played.length).toBeGreaterThan(0);
  expect(played.every((path) => /^\/api\/media\/timeline-e2e-\d+\.wav$/.test(path))).toBe(true);
  expect(played).not.toContain("/api/media/takes/take-e2e-1.wav");
  expect(played).not.toContain("/api/media/takes/take-e2e-2.wav");
  await expect(page.locator(".line-card.is-cue-member.is-playing")).toHaveCount(2);
  await page.getByRole("button", { name: "■ 停止" }).click();
});

test("three-digit circular line number stays centered while compressed", async ({ page }) => {
  await page.goto("/");
  const number = page.locator(".line-number").first();
  await number.locator(".circle-number-glyph").evaluate((glyph) => {
    glyph.textContent = "103";
    glyph.classList.add("is-three-digits");
  });
  const geometry = await number.evaluate((element) => {
    const glyph = element.querySelector<HTMLElement>(".circle-number-glyph");
    if (!glyph) throw new Error("number glyph is missing");
    const circle = element.getBoundingClientRect();
    const text = glyph.getBoundingClientRect();
    return {
      circleCenter: circle.left + circle.width / 2,
      textCenter: text.left + text.width / 2,
      transform: getComputedStyle(glyph).transform,
    };
  });
  expect(Math.abs(geometry.circleCenter - geometry.textCenter)).toBeLessThan(0.5);
  expect(geometry.transform).not.toBe("none");
});
