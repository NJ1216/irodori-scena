import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { testToneWav } from "./audio-fixtures";
import { installMockApi } from "./mock-api";
import type { LoraInputRow } from "../../src/types/lora";

const fixtureRows: LoraInputRow[] = process.env.SCENA_LORA_QA_ROWS
  ? JSON.parse(readFileSync(process.env.SCENA_LORA_QA_ROWS, "utf8"))
  : Array.from({ length: 100 }, (_, index) => ({
      id: `fixture-${index}`,
      wavName: `${String(index + 1).padStart(3, "0")}.wav`,
      textName: `${index}.txt`,
      text: `確認用の台詞 ${index + 1}。音声と対応を確認します。`,
      caption: "",
      speakerId: "speaker-1",
      durationSeconds: 6,
      issues: [],
      audioUrl: `/fixture/audio/${index}.wav`,
    }));

for (const viewport of [
  { width: 1280, height: 900 },
  { width: 1440, height: 960 },
]) {
  test(`100 materials stay compact and editable at ${viewport.width}×${viewport.height}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await installMockApi(page);
    // Replace only the native directory-picker boundary inside this isolated browser.
    // No user window, local source folder or training endpoint is touched.
    await page.route("**/src/api-runtime.ts", async (route) => {
      const response = await route.fetch();
      const body = (await response.text()).replace(/export async function chooseDirectory\([\s\S]*?(?=export async function chooseCastFiles)/, 'export async function chooseDirectory() { return "/fixture/samples"; }\n');
      await route.fulfill({ response, body });
    });
    const rows = fixtureRows.map((row) => ({ ...row }));
    rows[1].text = "長い台詞。".repeat(1000);
    rows[2] = { ...rows[2], text: "", textName: null, issues: ["TXT がありません。本文を入力してください。"] };
    rows[3].issues = ["WAV は120秒以内にしてください。"];
    rows[4] = { ...rows[4], relativePath: "深いフォルダ/".repeat(20) + rows[4].wavName, blocked: true, issues: ["同名候補が複数あります。"] };
    let trainingRequests = 0;
    await page.route("**/api/lora/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/lora/jobs" && route.request().method() === "POST") trainingRequests += 1;
      const body = path.endsWith("/inputs/folder") ? { datasetId: "fixture", folderName: "samples", ignoredTextCount: 1, rows } : path.endsWith("/status") ? { supported: true } : [];
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    });
    let audioRequests = 0;
    await page.route("**/fixture/audio/**", async (route) => {
      audioRequests += 1;
      await route.fulfill({ contentType: "audio/wav", body: testToneWav(2) });
    });
    await page.goto("/");
    const automatic = page.getByRole("button", { name: "自動生成", exact: true });
    if ((await automatic.getAttribute("aria-pressed")) === "true") await automatic.click();
    await page.locator(".project-menu").hover();
    await page.getByRole("button", { name: "LoRA管理…", exact: true }).click();
    await page.getByRole("button", { name: /LoRAを学習する/ }).click();
    await page.getByRole("button", { name: /フォルダを選択/ }).click();
    await page.getByRole("button", { name: "内容を確認する" }).click();
    const table = page.getByRole("table");
    await expect(table.locator("tbody > tr")).toHaveCount(100);
    await expect(table.getByRole("columnheader")).toHaveText(["ファイル", "台詞", "再生", "状態", "除外"]);
    expect(await page.locator(".lora-input-scroll").evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
    const next = page.getByRole("button", { name: "名前と学習へ" });
    await page.screenshot({ path: testInfo.outputPath("minimum-before-check.png") });
    await expect(next).toBeInViewport();
    expect(
      await table
        .locator("tbody > tr")
        .first()
        .evaluate((el) => el.getBoundingClientRect().height),
    ).toBeLessThanOrEqual(44);
    expect(
      await table
        .locator("tbody > tr")
        .nth(1)
        .evaluate((el) => el.getBoundingClientRect().height),
    ).toBeLessThanOrEqual(44);
    await page.screenshot({ path: testInfo.outputPath("100-materials-minimum.png") });
    expect(audioRequests).toBe(0);
    await table.getByRole("button", { name: `${rows[0].relativePath ?? rows[0].wavName}を再生` }).click();
    await expect(table.getByRole("button", { name: `${rows[0].relativePath ?? rows[0].wavName}を停止` })).toHaveText("■");
    expect(audioRequests).toBe(1);
    await table.getByRole("button", { name: `${rows[0].relativePath ?? rows[0].wavName}を停止` }).click();
    await table.getByRole("button", { name: `${rows[1].wavName}の台詞を編集` }).click();
    await page.getByLabel("台詞", { exact: true }).fill("変更した行だけの台詞");
    await table.getByRole("button", { name: `${rows[0].wavName}の台詞を編集` }).click();
    await expect(page.getByLabel("台詞", { exact: true })).toHaveValue(rows[0].text);
    await table.getByRole("button", { name: `${rows[1].wavName}の台詞を編集` }).click();
    await expect(page.getByLabel("台詞", { exact: true })).toHaveValue("変更した行だけの台詞");
    await page.screenshot({ path: testInfo.outputPath("selected-row-edit.png") });
    await next.click();
    await expect(page.getByRole("alert")).toContainText("本文");
    for (const row of rows.slice(2, 5)) await page.getByRole("checkbox", { name: `${row.relativePath ?? row.wavName}を除外` }).check();
    await page.locator(".lora-input-scroll").evaluate((el) => {
      el.scrollTop = el.scrollHeight;
    });
    await expect(table.getByRole("button", { name: `${rows[99].wavName}を確認` })).toBeInViewport();
    await expect(next).toBeInViewport();
    await expect(table.getByRole("columnheader", { name: "台詞" })).toBeInViewport();
    await page.screenshot({ path: testInfo.outputPath("100-materials-bottom.png") });
    await next.click();
    await expect(page.getByLabel("LoRA名")).toBeVisible();
    expect(trainingRequests).toBe(0);
  });
}
