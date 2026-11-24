import { expect, test } from "@playwright/test";
import metadata from "../../release-metadata.json" with { type: "json" };
import { installMockApi } from "./mock-api";

for (const viewport of [
  { width: 1280, height: 900 },
  { width: 1440, height: 960 },
]) {
  test(`license overlay fits ${viewport.width} with compressed offline notices`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await installMockApi(page);
    const requests: string[] = [];
    page.on("requestfinished", (request) => {
      if (request.url().includes("third-party-licenses")) requests.push(request.url());
    });
    await page.goto("/");
    await expect(page.getByRole("button", { name: /連続再生/ })).toBeVisible();
    const trigger = page.getByRole("button", { name: "バージョン情報", exact: true });
    await expect(trigger).not.toHaveAttribute("title");
    await trigger.focus();
    const menu = page.getByLabel("バージョン情報メニュー");
    await expect(menu).toContainText(`作者NJ本体 Versionv${metadata.version}`);
    await page.screenshot({ path: testInfo.outputPath("version-menu.png") });
    const licenseLink = menu.getByRole("button", { name: "ライセンス情報", exact: true });
    await licenseLink.click();
    const dialog = page.getByRole("dialog", { name: "ライセンス情報", exact: true });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel("ライセンス本文")).toContainText("Copyright (c) 2026 NJ");
    const bounds = await dialog.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.y).toBeGreaterThanOrEqual(0);
    expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(viewport.height);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width);
    await expect(dialog.getByRole("navigation", { name: "使用ライブラリ" }).getByRole("button")).toHaveCount(30);
    await page.screenshot({ path: testInfo.outputPath("license-application.png") });
    await dialog.getByRole("searchbox").fill("react");
    const react = dialog.getByRole("button", { name: /^react 19/ });
    await react.scrollIntoViewIfNeeded();
    const beforeHover = await react.boundingBox();
    await react.hover();
    expect(await react.boundingBox()).toEqual(beforeHover);
    await react.click();
    await expect(dialog.getByLabel("ライセンス本文")).toContainText("Permission");
    expect(requests).toHaveLength(1);
    expect(requests[0]).toContain("third-party-licenses.json.gz");
    await page.screenshot({ path: testInfo.outputPath("license-selected.png") });
    await page.context().setOffline(true);
    await dialog.getByRole("searchbox").fill("no-match-library-name");
    await expect(dialog).toContainText("0 件");
    await expect(dialog.getByRole("button", { name: "次のページ" })).toBeDisabled();
    await dialog.getByRole("button", { name: "閉じる", exact: true }).focus();
    await page.keyboard.press("Tab");
    await expect(dialog.getByRole("searchbox")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });
}

test("license overlay supports loading, failed download, retry and long text", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await installMockApi(page);
  const resource = "**/third-party-licenses.json.gz";
  await page.route(resource, (route) => route.fulfill({ status: 503, body: "unavailable" }));
  await page.goto("/");
  await page.getByRole("button", { name: "バージョン情報", exact: true }).focus();
  await page.getByRole("button", { name: "ライセンス情報", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "ライセンス情報", exact: true });
  await expect(dialog.getByRole("alert")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("license-error.png") });
  await page.unroute(resource);
  let release!: () => void;
  const barrier = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(resource, async (route) => {
    await barrier;
    await route.continue();
  });
  await dialog.getByRole("button", { name: "再読み込み" }).click();
  await expect(dialog.getByRole("status")).toContainText("読み込み中");
  await page.screenshot({ path: testInfo.outputPath("license-loading.png") });
  release();
  await expect(dialog.getByLabel("ライセンス本文")).toContainText("Copyright (c) 2026 NJ");
  await dialog.getByRole("searchbox").fill("numpy");
  await dialog
    .getByRole("button", { name: /^numpy / })
    .first()
    .click();
  const body = dialog.getByLabel("ライセンス本文");
  await expect(body).toContainText("Copyright");
  await body.hover();
  await page.mouse.wheel(0, 1000);
  await expect.poll(() => body.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  await expect(dialog.getByRole("button", { name: "閉じる", exact: true })).toBeInViewport();
  await page.screenshot({ path: testInfo.outputPath("license-long-text.png") });
});
