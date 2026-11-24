import { expect, test } from "@playwright/test";
import { openCasts } from "./cast-deletion-fixture";

async function canvasHasVisiblePixels(canvas: import("@playwright/test").Locator) {
  return canvas.evaluate((element) => {
    const image = element as HTMLCanvasElement;
    const pixels = image.getContext("2d")!.getImageData(0, 0, image.width, image.height).data;
    for (let index = 3; index < pixels.length; index += 4) if (pixels[index]) return true;
    return false;
  });
}

for (const delayNextAvatar of [false, true])
  test(`consecutive deletions animate both casts (next image loading: ${delayNextAvatar})`, async ({ page }, info) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.emulateMedia({ reducedMotion: "no-preference" });
    const calls = await openCasts(page, false, false, true, undefined, delayNextAvatar);
    for (const name of ["佐倉 紗良", "水瀬 蓮"]) {
      await expect(page.locator(".cast-notebook-spread h2")).toHaveText(name);
      if (name === "水瀬 蓮" && !delayNextAvatar) await page.waitForTimeout(1500);
      const remove = page.locator(".cast-notebook-actions").getByRole("button", { name: "削除", exact: true });
      await remove.click();
      await remove.click();
      const region = page.locator(".cast-deletion-region");
      await expect(region.getByRole("status")).toHaveText(`「${name}」を削除しました`);
      await expect(region).toHaveClass(/has-particles/);
      const canvas = page.locator(".cast-deletion-particle-layer .cast-deletion-canvas");
      await expect(canvas).toHaveCount(1);
      expect(await canvasHasVisiblePixels(canvas)).toBe(true);
      const first = await canvas.evaluate((element) => (element as HTMLCanvasElement).toDataURL());
      await page.waitForTimeout(350);
      expect(await canvas.evaluate((element) => (element as HTMLCanvasElement).toDataURL())).not.toBe(first);
      const notebookVisible = await page.evaluate(() => {
        const top = document.querySelector(".cast-notebook-spread")!.getBoundingClientRect().top;
        const headerBottom = document.querySelector(".app-header")!.getBoundingClientRect().bottom;
        return top >= headerBottom;
      });
      expect(notebookVisible).toBe(true);
      await page.screenshot({ path: info.outputPath(`consecutive-${name}.png`), animations: "allow" });
      await expect(region.getByRole("status")).toHaveCount(0);
    }
    expect(calls()).toBe(2);
    await expect(page.getByText("まだ登録されていません。候補を採用するか、WAVを登録してください。")).toBeVisible();
  });

for (const width of [1280, 1600]) {
  test(`deletion dissolves the old page before selecting another cast at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: width === 1280 ? 900 : 1000 });
    await page.emulateMedia({ reducedMotion: "no-preference" });
    const calls = await openCasts(page, false, false, true);
    const remove = page.locator(".cast-notebook-actions").getByRole("button", { name: "削除", exact: true });
    await remove.click();
    expect(calls()).toBe(0);
    await expect(page.locator(".cast-deletion-region > div").first()).not.toHaveAttribute("inert", "");
    await expect(remove).toBeEnabled();
    await remove.click();
    await expect(page.locator(".cast-deletion-region").getByRole("status")).toHaveText("「佐倉 紗良」を削除しました");
    expect(calls()).toBe(1);
    // The stored list has already changed, but the visible page is retained and inert.
    const spread = page.locator(".cast-notebook-spread");
    await expect(spread.locator("h2")).toHaveText("佐倉 紗良");
    await expect(page.locator(".cast-deletion-region > div").first()).toHaveAttribute("inert", "");
    await expect(page.locator(".cast-deletion-region")).toHaveClass(/has-particles/);
    const canvas = page.locator(".cast-deletion-canvas");
    await expect(canvas).toHaveCount(1);
    expect(await canvasHasVisiblePixels(canvas)).toBe(true);
    const firstFrame = await canvas.evaluate((element) => (element as HTMLCanvasElement).toDataURL());
    await page.screenshot({ path: info.outputPath("cast-start.png"), animations: "allow" });
    await page.waitForTimeout(650);
    expect(await canvas.evaluate((element) => (element as HTMLCanvasElement).toDataURL())).not.toBe(firstFrame);
    await page.screenshot({ path: info.outputPath("cast-dissolving.png"), animations: "allow" });
    await expect(page.locator(".cast-deletion-region").getByRole("status")).toHaveCount(0);
    await expect(spread.locator("h2")).toHaveText("水瀬 蓮");
    await expect(page.getByRole("button", { name: "水瀬 蓮", exact: true })).toBeFocused();
    await page.locator(".cast-notebook-actions").getByRole("button", { name: "設定を編集" }).click();
    await expect(page.getByRole("heading", { name: "キャストの設定を編集" })).toBeVisible();
  });
}

test("failed deletion does not dissolve the page", async ({ page }) => {
  const calls = await openCasts(page, true);
  const remove = page.locator(".cast-notebook-actions").getByRole("button", { name: "削除", exact: true });
  await remove.click();
  await remove.click();
  await expect(page.locator(".notice")).toContainText("キャストを削除できませんでした:");
  await expect(page.locator(".notice")).toBeVisible();
  expect(calls()).toBe(1);
  await expect(page.locator(".cast-notebook-spread h2")).toHaveText("佐倉 紗良");
  await expect(page.locator(".cast-deletion-region.is-dissolving")).toHaveCount(0);
  await expect(remove).toBeFocused();
});

test("unavailable avatar preparation deletes with a visible CSS fallback", async ({ page }) => {
  const calls = await openCasts(page, false, false, true);
  await page.route("**/api/media/test-avatar-*.png*", (route) => route.fulfill({ status: 404 }));
  const remove = page.locator(".cast-notebook-actions").getByRole("button", { name: "削除", exact: true });
  await remove.click();
  await remove.click();
  await expect(page.locator(".cast-deletion-region.is-css-fallback").getByRole("status")).toHaveText("「佐倉 紗良」を削除しました");
  expect(calls()).toBe(1);
  await expect(page.locator(".cast-notebook-spread h2")).toHaveText("佐倉 紗良");
  await expect(page.locator(".cast-deletion-canvas")).toHaveCount(0);
});

test("reduced motion still uses the product deletion animation", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openCasts(page, false, true);
  const remove = page.locator(".cast-notebook-actions").getByRole("button", { name: "削除", exact: true });
  await remove.click();
  await remove.click();
  await expect(page.locator(".cast-deletion-region").getByRole("status")).toHaveText("「佐倉 紗良」を削除しました");
  await expect(page.locator(".cast-deletion-region")).toHaveClass(/has-particles/);
  await expect(page.getByText("まだ登録されていません。候補を採用するか、WAVを登録してください。")).toBeVisible();
});

test("Canvas unavailability deletes with a visible CSS fallback", async ({ page }) => {
  const calls = await openCasts(page);
  await page.evaluate(() => {
    HTMLCanvasElement.prototype.getContext = () => null;
  });
  const remove = page.locator(".cast-notebook-actions").getByRole("button", { name: "削除", exact: true });
  await remove.click();
  await remove.click();
  await expect(page.locator(".cast-deletion-region.is-css-fallback").getByRole("status")).toHaveText("「佐倉 紗良」を削除しました");
  await expect(page.locator(".cast-deletion-canvas")).toHaveCount(0);
  await expect(page.locator(".cast-notebook-spread h2")).toHaveText("佐倉 紗良");
  expect(calls()).toBe(1);
});
