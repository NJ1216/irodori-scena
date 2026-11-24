import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test("persists and clears line-local CFG overrides without adding empty keys", async ({ page }) => {
  const savedProjects: Array<{ scenes: Array<{ lines: Array<Record<string, unknown>> }> }> = [];
  page.on("request", (request) => {
    if (request.method() === "PUT" && new URL(request.url()).pathname === "/api/project") savedProjects.push(request.postDataJSON().project);
  });
  await installMockApi(page);
  await page.goto("/");
  const line = page.locator(".line-card").first();
  await line.locator(".line-meta").hover();
  await expect(line.locator(".line-cfg-disclosure")).toHaveCSS("width", "20px");
  await line.getByRole("button", { name: "行ごとのCFG設定を表示" }).click();
  const textCfg = line.getByLabel("発話行ごとのtextCfg（台詞への追従）");
  const voiceCfg = line.getByLabel("発話行ごとのvoiceCfg（基準ボイスへの追従）");
  const captionCfg = line.getByLabel("発話行ごとのcaptionCfg（ト書きへの追従）");
  await textCfg.fill("4.2");
  await voiceCfg.fill("6.3");
  await captionCfg.fill("7.4");
  await captionCfg.blur();
  await expect.poll(() => savedProjects.at(-1)?.scenes[0].lines[0]).toMatchObject({ textCfg: 4.2, voiceCfg: 6.3, captionCfg: 7.4 });
  await page.locator(".line-card").nth(1).click();
  await expect(line.getByRole("button", { name: "行ごとのCFG設定を表示" })).toHaveAttribute("aria-expanded", "false");
  await expect(line.locator(".line-cfg-control")).toHaveCount(3);
  await expect(line.locator(".line-cfg-disclosure")).toHaveCSS("width", "0px");
  await expect(line.locator(".line-cfg-disclosure")).toHaveCSS("margin-right", "0px");
  await line.locator(".line-meta").hover();
  await expect(line.locator(".line-cfg-disclosure")).toHaveCSS("width", "20px");
  await line.getByRole("button", { name: "行ごとのCFG設定を表示" }).click();
  await textCfg.fill("");
  await voiceCfg.fill("");
  await captionCfg.fill("");
  await captionCfg.blur();
  await expect
    .poll(() => {
      const saved = savedProjects.at(-1)?.scenes[0].lines[0];
      return saved && !Object.hasOwn(saved, "textCfg") && !Object.hasOwn(saved, "voiceCfg") && !Object.hasOwn(saved, "captionCfg");
    })
    .toBe(true);
});
