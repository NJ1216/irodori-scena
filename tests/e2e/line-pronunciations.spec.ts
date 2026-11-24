import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test.beforeEach(async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");
});

async function selectText(page: import("@playwright/test").Page, line: import("@playwright/test").Locator, start: number, end: number) {
  const point = await line.evaluate(
    (element, offsets) => {
      const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT, {
        acceptNode: (node) => (node.parentElement?.closest("rt") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
      });
      const nodes: Text[] = [];
      let node: Node | null;
      while ((node = walker.nextNode())) nodes.push(node as Text);
      const locate = (offset: number) => {
        let rest = offset;
        for (const text of nodes) {
          if (rest <= (text.textContent ?? "").length) return { text, offset: rest };
          rest -= (text.textContent ?? "").length;
        }
        throw new Error("selection offset was outside the line");
      };
      const first = locate(offsets.start);
      const last = locate(offsets.end);
      const range = document.createRange();
      range.setStart(first.text, first.offset);
      range.setEnd(last.text, last.offset);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
      const rect = range.getBoundingClientRect();
      element.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX: rect.left, clientY: rect.bottom }));
      return { x: rect.left + Math.min(4, rect.width / 2), y: rect.top + rect.height / 2 };
    },
    { start, end },
  );
  await page.mouse.move(point.x, point.y);
}

async function hoverText(page: import("@playwright/test").Page, line: import("@playwright/test").Locator, target: string) {
  const point = await line.evaluate((element, value) => {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) => (node.parentElement?.closest("rt") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    let node: Node | null;
    while ((node = walker.nextNode())) {
      const index = (node.textContent ?? "").indexOf(value);
      if (index < 0) continue;
      const range = document.createRange();
      range.setStart(node, index);
      range.setEnd(node, index + value.length);
      const rect = range.getBoundingClientRect();
      return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    }
    throw new Error(`text was not found: ${value}`);
  }, target);
  await page.mouse.move(point.x, point.y);
}

test("shows an emoji effect tooltip in a line containing ruby", async ({ page }) => {
  const line = page.locator(".line-text-editor").first();
  await line.fill("東京😊へ");
  await selectText(page, line, 0, 2);
  await page.getByRole("button", { name: "読みを設定" }).click();
  await page.locator(".ruby-popover input").fill("とうきょう");
  await page.locator(".ruby-popover input").press("Enter");

  await hoverText(page, line, "😊");
  await expect(page.getByRole("tooltip", { name: "楽しげ" })).toBeVisible();
  await page.mouse.move(0, 0);
  await expect(page.locator(".emoji-tooltip")).toHaveCount(0);
});

test("opens the ruby editor only from the hovered selection action", async ({ page }) => {
  const line = page.locator(".line-text-editor").first();
  await line.fill("東京へ行く");
  await selectText(page, line, 0, 2);
  await expect(page.locator(".ruby-popover")).toHaveCount(0);
  const selectionAction = page.getByRole("button", { name: "読みを設定" });
  await expect(selectionAction).toBeVisible();
  const selectionBox = await page.evaluate(() => window.getSelection()?.getRangeAt(0).getBoundingClientRect().toJSON());
  const actionBox = await page.locator(".ruby-selection-action").boundingBox();
  expect(selectionBox).toBeTruthy();
  expect(actionBox).not.toBeNull();
  expect(actionBox!.x + actionBox!.width / 2).toBeCloseTo(selectionBox!.x + selectionBox!.width / 2, 0);
  await expect(selectionAction).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  const restingColor = await selectionAction.evaluate((element) => getComputedStyle(element).color);
  await selectionAction.hover();
  await expect.poll(() => selectionAction.evaluate((element) => getComputedStyle(element).color)).not.toBe(restingColor);
  await selectionAction.click();
  await expect(page.locator(".ruby-popover")).toBeVisible();
  const inputStart = await page.locator(".ruby-popover input").evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.left + Number.parseFloat(style.borderLeftWidth) + Number.parseFloat(style.paddingLeft);
  });
  expect(inputStart).toBeCloseTo(selectionBox!.x, 0);
  await expect(page.locator(".ruby-popover button")).toHaveCount(0);
  await expect(page.locator(".ruby-popover")).not.toContainText("ルビを設定");
  await page.locator(".ruby-popover input").fill("とうきょう");
  await page.locator(".ruby-popover input").press("Enter");
  await expect(line.locator("ruby")).toContainText("とうきょう");
  await expect(line.locator("ruby rt")).toHaveText("とうきょう");
  await expect(line.locator(".ruby-reading")).toHaveCSS("transform", /matrix\(0\.8, 0, 0, 1, 0, 2\)/);
  await line.locator("ruby").click();
  const rubyBox = await line.locator("ruby").boundingBox();
  const popoverBox = await page.locator(".ruby-popover").boundingBox();
  expect(rubyBox).not.toBeNull();
  expect(popoverBox).not.toBeNull();
  expect(popoverBox!.y + popoverBox!.height).toBeLessThanOrEqual(rubyBox!.y);
  await expect(page.locator(".ruby-popover")).not.toContainText("ルビを編集");
  await expect(page.getByRole("button", { name: "ルビを削除" })).toBeVisible();
  await page.locator(".ruby-popover input").fill("変更しない");
  await page.locator(".ruby-popover input").press("Escape");
  await expect(line.locator("ruby rt")).toHaveText("とうきょう");
  await line.locator("ruby").click();
  await page.locator(".ruby-popover input").fill("これも変更しない");
  await page.getByRole("button", { name: "プロジェクト" }).click();
  await expect(line.locator("ruby rt")).toHaveText("とうきょう");
  await line.locator("ruby").click();
  await page.getByRole("button", { name: "ルビを削除" }).click();
  await expect(line.locator("ruby")).toHaveCount(0);
});

test("recovers a text selection on hover and opens it with Command R", async ({ page }) => {
  const line = page.locator(".line-text-editor").first();
  await line.fill("東京へ行く");
  const point = await line.evaluate((element) => {
    const text = element.firstChild as Text;
    const range = document.createRange();
    range.setStart(text, 0);
    range.setEnd(text, 2);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    const rect = range.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  });

  await page.mouse.move(point.x, point.y);
  const action = page.getByRole("button", { name: "読みを設定" });
  await expect(action).toBeVisible();
  expect(await action.evaluate((element) => element.parentElement?.parentElement === document.body)).toBe(true);
  await page.keyboard.press("ControlOrMeta+r");
  const input = page.locator(".ruby-popover input");
  await expect(input).toBeVisible();
  expect(await input.evaluate((element) => element.parentElement?.parentElement === document.body)).toBe(true);
});

test("caps ruby compression at the three-reading-characters-per-base-character ratio", async ({ page }) => {
  const line = page.locator(".line-text-editor").first();
  await line.fill("東へ");
  await selectText(page, line, 0, 1);
  await page.getByRole("button", { name: "読みを設定" }).click();
  await page.locator(".ruby-popover input").fill("ひがし");
  await page.locator(".ruby-popover input").press("Enter");
  await expect(line.locator(".ruby-reading")).toHaveCSS("transform", /matrix\(0\.666667, 0, 0, 1, 0, 2\)/);
  await line.locator("ruby").click();
  await page.locator(".ruby-popover input").fill("ひがしの");
  await page.locator(".ruby-popover input").press("Enter");
  await expect(line.locator(".ruby-reading")).toHaveCSS("transform", /matrix\(0\.666667, 0, 0, 1, 0, 2\)/);
});

test("does not insert ruby readings into the line while editing its text", async ({ page }) => {
  const line = page.locator(".line-text-editor").first();
  await line.fill("東京へ行く");
  await selectText(page, line, 0, 2);
  await page.getByRole("button", { name: "読みを設定" }).click();
  await page.locator(".ruby-popover input").fill("とうきょう");
  await page.locator(".ruby-popover input").press("Enter");
  await line.evaluate((element) => {
    const tail = element.lastChild;
    if (!tail) throw new Error("line has no tail text");
    const range = document.createRange();
    range.selectNodeContents(tail);
    range.collapse(false);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  });
  await line.press("Backspace");
  await expect
    .poll(() =>
      line.evaluate((element) => {
        const copy = element.cloneNode(true) as HTMLElement;
        copy.querySelectorAll("rt").forEach((reading) => reading.remove());
        return copy.textContent;
      }),
    )
    .toBe("東京へ行");
  await expect(line.locator("ruby rt")).toHaveText("とうきょう");
});

test("keeps the caret out of ruby readings during keyboard navigation", async ({ page }) => {
  const line = page.locator(".line-text-editor").first();
  await line.fill("東京へ行く");
  await selectText(page, line, 0, 2);
  await page.getByRole("button", { name: "読みを設定" }).click();
  await page.locator(".ruby-popover input").fill("とうきょう");
  await page.locator(".ruby-popover input").press("Enter");
  await line.evaluate((element) => {
    const base = element.querySelector(".ruby-base")?.firstChild;
    if (!base) throw new Error("ruby base text was not found");
    element.focus();
    const range = document.createRange();
    range.selectNodeContents(base);
    range.collapse(false);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  });

  for (let step = 0; step < 4; step += 1) {
    await page.keyboard.press("ArrowRight");
    await expect
      .poll(() =>
        line.evaluate(() => {
          const node = window.getSelection()?.anchorNode;
          return node instanceof Element ? Boolean(node.closest("rt")) : Boolean(node?.parentElement?.closest("rt"));
        }),
      )
      .toBe(false);
  }
  await expect(line.locator("ruby rt")).toHaveText("とうきょう");
});

test("excludes ruby readings when selecting the line text", async ({ page }) => {
  const line = page.locator(".line-text-editor").first();
  await line.fill("東京へ行く");
  await selectText(page, line, 0, 2);
  await page.getByRole("button", { name: "読みを設定" }).click();
  await page.locator(".ruby-popover input").fill("とうきょう");
  await page.locator(".ruby-popover input").press("Enter");
  await selectText(page, line, 0, 3);
  await expect(line.locator("rt")).toHaveCSS("user-select", "none");
  const copied = await line.evaluate((element) => {
    const clipboard = new DataTransfer();
    element.dispatchEvent(new ClipboardEvent("copy", { bubbles: true, cancelable: true, clipboardData: clipboard }));
    return clipboard.getData("text/plain");
  });
  expect(copied).toBe("東京へ");
});

test("keeps native selection available for copy and hides the action outside it", async ({ page }) => {
  const line = page.locator(".line-text-editor").first();
  await line.fill("東京へ行く");
  await selectText(page, line, 0, 2);
  await expect(page.locator(".ruby-popover")).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => window.getSelection()?.toString())).toBe("東京");
  await page.evaluate(() =>
    document.addEventListener(
      "copy",
      () => {
        (window as typeof window & { copiedSelection?: string }).copiedSelection = window.getSelection()?.toString();
      },
      { once: true },
    ),
  );
  await page.keyboard.press("ControlOrMeta+c");
  await expect.poll(() => page.evaluate(() => (window as typeof window & { copiedSelection?: string }).copiedSelection)).toBe("東京");
  await page.mouse.move(0, 0);
  await expect(page.getByRole("button", { name: "読みを設定" })).toHaveCount(0);
  await line.click();
  await expect(page.getByRole("button", { name: "読みを設定" })).toHaveCount(0);
});

test("validates a multiline selection before opening the ruby editor", async ({ page }) => {
  const line = page.locator(".line-text-editor").first();
  await line.fill("東京\n大阪");
  await selectText(page, line, 1, 4);
  await page.getByRole("button", { name: "読みを設定" }).click();
  await expect(page.locator(".ruby-popover")).toHaveCount(0);
  await expect(page.locator(".notice")).toContainText("改行をまたぐ範囲");
});

test("rejects a selection that partially overlaps an existing ruby", async ({ page }) => {
  const line = page.locator(".line-text-editor").first();
  await line.fill("東京大阪");
  await selectText(page, line, 0, 2);
  await page.getByRole("button", { name: "読みを設定" }).click();
  await page.locator(".ruby-popover input").fill("とうきょう");
  await page.locator(".ruby-popover input").press("Enter");
  await selectText(page, line, 1, 3);
  await page.getByRole("button", { name: "読みを設定" }).click();
  await expect(page.locator(".ruby-popover")).toHaveCount(0);
  await expect(page.locator(".notice")).toContainText("設定済みの読みと重なる範囲");
  await expect(line.locator("ruby rt")).toHaveText("とうきょう");
});
