import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test("focuses the search input when Command F opens it for the first time", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");
  await expect(page.getByRole("button", { name: "▶ 連続再生" })).toBeVisible();
  await expect(page.locator(".line-text-editor").first()).toBeVisible();

  await page.evaluate(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "f", code: "KeyF", metaKey: true, bubbles: true })));

  const search = page.getByRole("textbox", { name: "検索" });
  await expect(search).toBeFocused();
  await page.keyboard.type("こんにちは");
  await expect(search).toHaveValue("こんにちは");
});

test("closes search with Escape after focus moves outside the search bar", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");
  await expect(page.locator(".line-text-editor").first()).toBeVisible();
  await page.evaluate(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "f", code: "KeyF", metaKey: true, bubbles: true })));
  await expect(page.getByRole("search")).toBeVisible();
  await page.locator(".line-card").first().focus();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("search")).toHaveCount(0);
  await expect(page.locator(".script-search-dim-layer")).toHaveCount(0);
});

test("opens the search bar as an overlay without moving dialogue lines", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");
  const firstLine = page.locator(".line-card").first();
  await expect(firstLine).toBeVisible();
  const before = await firstLine.boundingBox();
  const scrollBefore = await page.locator(".script-canvas").evaluate((element) => element.scrollTop);

  await page.evaluate(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "f", code: "KeyF", metaKey: true, bubbles: true })));
  await expect(page.getByRole("search")).toBeVisible();

  const after = await firstLine.boundingBox();
  const scrollAfter = await page.locator(".script-canvas").evaluate((element) => element.scrollTop);
  const dimmer = await page.locator(".app-shell--script").evaluate((element) => {
    const style = getComputedStyle(element, "::before");
    return { content: style.content, position: style.position, pointerEvents: style.pointerEvents, top: style.top, bottom: style.bottom };
  });
  expect(after?.y).toBe(before?.y);
  expect(scrollAfter).toBe(scrollBefore);
  expect(dimmer.content).toBe('\"\"');
  expect(dimmer.position).toBe("fixed");
  expect(dimmer.pointerEvents).toBe("none");
  expect(parseFloat(dimmer.top)).toBeGreaterThan(0);
  expect(dimmer.bottom).toBe("36px");
});

test("repaints and pulses the current match after virtual scrolling", async ({ page }) => {
  await page.unroute("**/api/**");
  await installMockApi(page, { lineCount: 80 });
  await page.goto("/");
  await expect(page.locator(".line-text-editor").first()).toBeVisible();
  await page.evaluate(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "f", code: "KeyF", metaKey: true, bubbles: true })));
  await page.getByRole("textbox", { name: "検索" }).fill("40");

  const target = page.locator('[data-line-id="line-40"]');
  await expect(target).toBeVisible();
  const focusWindow = page.locator(".script-search-focus-window");
  await expect(focusWindow).toBeVisible();
  const focusWindowStyle = await focusWindow.evaluate((element) => ({ borderRadius: getComputedStyle(element).borderRadius, boxShadow: getComputedStyle(element).boxShadow }));
  expect(focusWindowStyle.borderRadius).not.toBe("0px");
  expect(focusWindowStyle.boxShadow).not.toBe("none");
  await expect
    .poll(async () => {
      const [lineBox, windowBox] = await Promise.all([target.boundingBox(), focusWindow.boundingBox()]);
      if (!lineBox || !windowBox) return false;
      return Math.abs(lineBox.x - windowBox.x) < 1 && Math.abs(lineBox.y - windowBox.y) < 1 && Math.abs(lineBox.width - windowBox.width) < 1 && Math.abs(lineBox.height - windowBox.height) < 1;
    })
    .toBe(true);
  await expect
    .poll(() =>
      page.evaluate(() => {
        const canvas = document.querySelector<HTMLElement>(".script-canvas");
        const line = document.querySelector<HTMLElement>('[data-line-id="line-40"]');
        if (!canvas || !line) return Number.POSITIVE_INFINITY;
        const canvasRect = canvas.getBoundingClientRect();
        const lineRect = line.getBoundingClientRect();
        return Math.abs(lineRect.top + lineRect.height / 2 - (canvasRect.top + canvasRect.height / 2));
      }),
    )
    .toBeLessThan(80);
  await expect
    .poll(() =>
      page.evaluate(() => {
        const highlights = (CSS as typeof CSS & { highlights?: Map<string, { size: number }> }).highlights;
        return highlights?.get("script-search-current")?.size ?? 0;
      }),
    )
    .toBe(1);
  const pulse = page.locator(".script-search-pulse");
  await expect(pulse).toHaveCount(1);
  expect(await pulse.evaluate((element) => getComputedStyle(element).animationName)).toBe("scena-search-word-pulse");
});

test("releases search-driven scrolling when the search bar closes", async ({ page }) => {
  await page.unroute("**/api/**");
  await installMockApi(page, { lineCount: 80 });
  await page.goto("/");
  await expect(page.locator(".line-text-editor").first()).toBeVisible();
  await page.evaluate(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "f", code: "KeyF", metaKey: true, bubbles: true })));
  await page.getByRole("textbox", { name: "検索" }).fill("80");
  await expect(page.locator('[data-line-id="line-80"]')).toBeVisible();
  await page.getByRole("button", { name: "検索を閉じる" }).click();

  const canvas = page.locator(".script-canvas");
  await page.waitForTimeout(100);
  await canvas.evaluate((element) => element.scrollTo({ top: 0, behavior: "instant" }));
  await expect.poll(() => canvas.evaluate((element) => element.scrollTop)).toBeLessThan(100);
  await canvas.evaluate((element) => element.scrollTo({ top: 600, behavior: "instant" }));
  await page.waitForTimeout(500);
  expect(await canvas.evaluate((element) => element.scrollTop)).toBeGreaterThan(500);
  await expect(page.locator(".script-search-pulse")).toHaveCount(0);
  await expect(page.locator(".script-search-focus-window")).toHaveCount(0);
});
