import { expect, test, type Page } from "@playwright/test";
import { installMockApi } from "./mock-api";

function stereoWav() {
  const sampleRate = 8_000;
  const frames = sampleRate * 2;
  const bytes = Buffer.alloc(44 + frames * 4);
  bytes.write("RIFF", 0);
  bytes.writeUInt32LE(bytes.length - 8, 4);
  bytes.write("WAVEfmt ", 8);
  bytes.writeUInt32LE(16, 16);
  bytes.writeUInt16LE(1, 20);
  bytes.writeUInt16LE(2, 22);
  bytes.writeUInt32LE(sampleRate, 24);
  bytes.writeUInt32LE(sampleRate * 4, 28);
  bytes.writeUInt16LE(4, 32);
  bytes.writeUInt16LE(16, 34);
  bytes.write("data", 36);
  bytes.writeUInt32LE(frames * 4, 40);
  for (let frame = 0; frame < frames; frame += 1) {
    const wave = Math.sin((frame * Math.PI * 2 * 440) / sampleRate);
    bytes.writeInt16LE(Math.round(wave * 16_000), 44 + frame * 4);
    bytes.writeInt16LE(Math.round(wave * 4_000), 46 + frame * 4);
  }
  return bytes;
}

async function expectUnifiedStereoMeter(page: Page) {
  const meter = page.getByLabel("マスター L/R レベル");
  await expect(page.getByRole("meter", { name: "Lチャンネル" })).toBeVisible();
  await expect(page.getByRole("meter", { name: "Rチャンネル" })).toBeVisible();
  await expect(meter).not.toHaveAttribute("title");
  const box = meter.locator(".master-meter-box");
  await expect(box).toHaveCSS("border-top-width", "1px");
  await expect(box).toHaveCSS("border-radius", "999px");
  expect((await box.boundingBox())!.height).toBe((await page.locator(".unified-memory-bar").first().boundingBox())!.height);
  const rows = meter.locator(".master-meter-track");
  const [left, right] = await Promise.all([rows.nth(0).boundingBox(), rows.nth(1).boundingBox()]);
  expect(Math.round(left!.y + left!.height)).toBe(Math.round(right!.y));
  expect(left!.height).toBe(right!.height);
  await expect(meter).toHaveText("");
}

async function expectMasterAtRightEdge(page: Page) {
  const master = await page.getByLabel("マスター音声").boundingBox();
  const version = await page.getByRole("button", { name: "バージョン情報" }).boundingBox();
  expect(Math.round(master!.x)).toBeGreaterThanOrEqual(Math.round(version!.x + version!.width));
  const expressionLabel = await page.getByRole("button", { name: "表情パレット", exact: true }).locator("span").last().boundingBox();
  const shortcutGlyph = await page.getByRole("button", { name: "ショートカット" }).locator("span").first().boundingBox();
  const versionGlyph = await page.getByRole("button", { name: "バージョン情報" }).locator("span").boundingBox();
  const meter = await page.getByLabel("マスター L/R レベル").boundingBox();
  const menuGap = shortcutGlyph!.x - expressionLabel!.x - expressionLabel!.width;
  const meterGap = meter!.x - versionGlyph!.x - versionGlyph!.width;
  expect(Math.abs(menuGap - meterGap)).toBeLessThanOrEqual(2);
}

async function expectExpressionPaletteInteractions(page: Page) {
  const menu = page.getByRole("navigation", { name: "アプリケーションメニュー" });
  await menu.getByRole("button", { name: "表情パレット", exact: true }).hover();
  const expressionMenu = page.getByLabel("表情パレットメニュー");
  await expect(expressionMenu).toBeVisible();
  const expressionTriggerBox = await menu.getByRole("button", { name: "表情パレット", exact: true }).boundingBox();
  const expressionMenuBox = await expressionMenu.boundingBox();
  expect(expressionTriggerBox).not.toBeNull();
  expect(expressionMenuBox).not.toBeNull();
  await page.mouse.move(expressionTriggerBox!.x + expressionTriggerBox!.width / 2, expressionTriggerBox!.y);
  await page.mouse.move(expressionMenuBox!.x + expressionMenuBox!.width - 16, expressionMenuBox!.y + expressionMenuBox!.height - 8, { steps: 8 });
  await expect(expressionMenu).toBeVisible();
  const rowCounts = await expressionMenu.locator(".emoji-palette button").evaluateAll((buttons) => {
    const rows = new Map<number, number>();
    buttons.forEach((button) => rows.set(button.offsetTop, (rows.get(button.offsetTop) ?? 0) + 1));
    return [...rows.values()];
  });
  expect(rowCounts).toEqual([23, 22]);

  const lineEditor = page.locator(".line-text-editor").first();
  await lineEditor.focus();
  await menu.getByRole("button", { name: "表情パレット", exact: true }).click();
  await expect(lineEditor).toBeFocused();
  await expressionMenu.getByRole("button", { name: "表情パレットをピン留め" }).click();
  await expect(lineEditor).toBeFocused();
  await expressionMenu.locator(".emoji-palette button").first().click();
  await expect(lineEditor).toBeFocused();
  await menu.getByRole("button", { name: "バージョン情報" }).hover();
  await expect(expressionMenu).toBeVisible();

  await page.keyboard.press("F3");
  await expect(expressionMenu).toBeHidden();
  await expect(expressionMenu.locator(".main-window-submenu-pin")).toHaveAttribute("aria-pressed", "true");
  await menu.getByRole("button", { name: "表情パレット", exact: true }).hover();
  await expect(expressionMenu).toBeVisible();
  await page.keyboard.press("F3");
  await expect(expressionMenu).toBeHidden();
  await page.keyboard.press("F3");
  await expect(expressionMenu).toBeVisible();

  const emojiBox = await expressionMenu.locator(".emoji-palette button").nth(1).boundingBox();
  const editorBox = await lineEditor.boundingBox();
  expect(emojiBox).not.toBeNull();
  expect(editorBox).not.toBeNull();
  const beforeDrop = await lineEditor.innerText();
  await page.mouse.move(emojiBox!.x + emojiBox!.width / 2, emojiBox!.y + emojiBox!.height / 2);
  await page.mouse.down();
  await page.mouse.move(editorBox!.x + 10, editorBox!.y + editorBox!.height / 2, { steps: 8 });
  await expect(page.locator("html")).toHaveClass(/is-dragging-expression-emoji/);
  await expect(lineEditor).toHaveClass(/is-emoji-drop-target/);
  await page.mouse.up();
  expect(await lineEditor.innerText()).toBe(`😮‍💨${beforeDrop}`);
  await expect(page.locator("html")).not.toHaveClass(/is-dragging-expression-emoji/);
}

test("shows the fixed one-line main window footer menu", async ({ page }) => {
  await installMockApi(page);
  let availableBytes = 40_000_000_000;
  await page.route("**/api/system/memory", async (route) =>
    route.fulfill({
      json: {
        kind: "unified",
        totalBytes: 100_000_000_000,
        availableBytes,
        otherUsedBytes: 30_000_000_000,
        scenaAppBytes: 10_000_000_000,
        llmBytes: 15_000_000_000,
        ttsBytes: 5_000_000_000,
        metalOwner: "llm",
        gpuUtilizationPercent: 42,
        sampledAt: 1,
      },
    }),
  );
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");

  const footer = page.locator(".main-window-footer");
  const menu = page.getByRole("navigation", { name: "アプリケーションメニュー" });
  await expect(footer).toBeVisible();
  await expect(footer).toHaveCSS("position", "fixed");
  await expectUnifiedStereoMeter(page);
  await expect(menu.getByRole("button")).toHaveCount(4);
  await expect(menu.getByRole("button", { name: "セッションtoken使用量" })).toHaveText("token 0");
  await expect(page.locator(".speaker-rail .emoji-palette, .speaker-rail .shortcut-card")).toHaveCount(0);
  const memoryBar = footer.locator(".unified-memory-bar").first();
  await expect(memoryBar.locator(".unified-memory-track")).toHaveCSS("border-top-color", "rgb(141, 137, 159)");
  await expect(memoryBar.locator(".memory-part-1")).toHaveCSS("background-color", "rgb(99, 200, 232)");
  await expect(memoryBar.locator(".memory-part-2")).toHaveCSS("background-color", "rgb(47, 189, 114)");
  await expect(memoryBar.locator(".memory-part-3")).toHaveCSS("background-color", "rgb(228, 182, 63)");
  await expect(memoryBar.locator(".memory-part-4")).toHaveCSS("background-color", "rgb(255, 255, 255)");
  const gpuMeter = footer.getByRole("meter", { name: "GPU使用率（1秒ごとに取得、直近3秒のピーク）" });
  await expect(gpuMeter).toHaveAttribute("aria-valuenow", "42");
  await expect(gpuMeter.locator("i")).toHaveAttribute("style", "width: 42%;");
  expect((await gpuMeter.boundingBox())?.width).toBe((await memoryBar.boundingBox())?.width);
  const memoryValue = footer.locator(".unified-memory-value");
  await expect(memoryValue).toHaveText("40.0GB 空き");
  await expect(memoryValue).toHaveCSS("text-align", "left");
  const memoryBarBox = await memoryBar.boundingBox();
  const memoryValueBox = await memoryValue.boundingBox();
  expect(Math.round(memoryValueBox!.x - memoryBarBox!.x - memoryBarBox!.width)).toBe(8);
  const gpuXBeforeMemoryDigitsChange = (await footer.locator(".gpu-meter").boundingBox())?.x;
  availableBytes = 9_000_000_000;
  await expect(memoryValue).toHaveText("9.0GB 空き");
  expect((await footer.locator(".gpu-meter").boundingBox())?.x).toBe(gpuXBeforeMemoryDigitsChange);

  const llmSegment = memoryBar.locator(".memory-part-hit-2");
  await expect(llmSegment).toHaveAttribute("data-tooltip", /^LLM \d+\.\dGB$/);
  const footerBeforeTooltip = await footer.boundingBox();
  const barBeforeTooltip = await memoryBar.boundingBox();
  await llmSegment.hover();
  await expect(llmSegment).toHaveCSS("position", "absolute");
  await expect.poll(() => llmSegment.evaluate((element) => getComputedStyle(element, "::after").opacity)).toBe("1");
  expect(await footer.boundingBox()).toEqual(footerBeforeTooltip);
  expect(await memoryBar.boundingBox()).toEqual(barBeforeTooltip);
  await page.mouse.move(640, 200);
  await expect.poll(() => llmSegment.evaluate((element) => getComputedStyle(element, "::after").opacity)).toBe("0");
  await llmSegment.focus();
  await expect(llmSegment).toBeFocused();
  await expect.poll(() => llmSegment.evaluate((element) => getComputedStyle(element, "::after").opacity)).toBe("1");
  expect(await footer.boundingBox()).toEqual(footerBeforeTooltip);
  await footer.locator(".gpu-meter").focus();
  await expect.poll(() => footer.locator(".gpu-meter").evaluate((element) => getComputedStyle(element, "::after").opacity)).toBe("1");
  expect(await footer.boundingBox()).toEqual(footerBeforeTooltip);
  const footerBox = await footer.boundingBox();
  const menuBox = await menu.boundingBox();
  expect(footerBox).not.toBeNull();
  expect(menuBox).not.toBeNull();
  await expectMasterAtRightEdge(page);
  expect(Math.round(footerBox!.y + footerBox!.height)).toBe(900);
  expect(menuBox!.x + menuBox!.width).toBeGreaterThan(1240);

  await menu.getByRole("button", { name: "セッションtoken使用量" }).focus();
  await menu.getByRole("button", { name: "セッションtoken使用量" }).hover();
  const tokenMenu = page.getByLabel("セッションtoken使用量メニュー");
  await expect(tokenMenu.getByRole("button", { name: "リセット" })).toBeVisible();
  await expect(tokenMenu).toHaveScreenshot("token-usage-menu.png", { animations: "disabled" });
  const resetRequest = page.waitForRequest((request) => new URL(request.url()).pathname === "/api/llm/session-usage/reset");
  await tokenMenu.getByRole("button", { name: "リセット" }).click();
  await expect((await resetRequest).method()).toBe("POST");

  await menu.getByRole("button", { name: "バージョン情報" }).hover();
  await expect(page.getByLabel("バージョン情報メニュー")).toBeVisible();
  await expect(page.getByLabel("バージョン情報メニュー")).toContainText("本体 Version");

  await expectExpressionPaletteInteractions(page);

  await menu.getByRole("button", { name: "ショートカット" }).hover();
  await expect(page.getByLabel("ショートカットメニュー")).toBeVisible();

  await page.setViewportSize({ width: 640, height: 700 });
  await expect(memoryBar).toHaveCSS("width", "36px");
  await expect(gpuMeter).toHaveCSS("width", "36px");
  await expect(footer).toBeVisible();
  await expect(footer).toHaveCSS("flex-wrap", "nowrap");
  expect(Math.round((await footer.boundingBox())!.height)).toBe(36);
});

test("adjusts and preserves the master volume without moving the footer", async ({ page }) => {
  await installMockApi(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  const footer = page.locator(".main-window-footer");
  const volume = page.getByRole("slider", { name: "マスターボリューム" });
  const before = await footer.boundingBox();
  await volume.focus();
  await expect(volume).not.toHaveAttribute("title");
  await page.keyboard.press("Home");
  await expect(volume).toHaveAttribute("aria-valuetext", "−∞ dB");
  await expect(volume).toHaveAttribute("style", "--master-knob-angle: -120deg;");
  await page.keyboard.press("End");
  await expect(volume).toHaveAttribute("style", "--master-knob-angle: 120deg;");
  const maxTransform = await volume.locator("i").evaluate((element) => getComputedStyle(element).transform);
  await page.keyboard.press("ArrowDown");
  await expect(volume).toHaveAttribute("aria-valuetext", "+5.9 dB");
  await expect(volume.locator("xpath=../output")).toHaveText("+5.9 dB");
  const knob = (await volume.boundingBox())!;
  await page.mouse.move(knob.x + knob.width / 2, knob.y + knob.height / 2);
  await page.mouse.down();
  await page.mouse.move(knob.x + knob.width / 2, knob.y + knob.height / 2 + 20);
  await page.mouse.up();
  await expect(volume).toHaveAttribute("aria-valuetext", "+4.9 dB");
  await expect.poll(() => volume.locator("i").evaluate((element) => getComputedStyle(element).transform)).not.toBe(maxTransform);
  expect(await footer.boundingBox()).toEqual(before);
  await page.reload();
  await expect(page.getByRole("slider", { name: "マスターボリューム" })).toHaveAttribute("aria-valuetext", "+4.9 dB");
});

test("shows post-fader stereo levels while a cross-origin take plays", async ({ page }) => {
  const audioUrl = "http://127.0.0.1:8788/test-stereo.wav";
  await page.route(audioUrl, (route) =>
    route.fulfill({
      body: stereoWav(),
      contentType: "audio/wav",
      headers: { "access-control-allow-origin": "http://127.0.0.1:5174" },
    }),
  );
  await installMockApi(page, { generatedTake: true, generatedTakeAudioUrl: audioUrl, timelineAudioUrl: audioUrl });
  await page.goto("/");
  const line = page.locator('[data-line-id="line-1"]');
  await line.hover();
  await line.locator(".line-play-toggle").click();
  const left = page.getByRole("meter", { name: "Lチャンネル" });
  const right = page.getByRole("meter", { name: "Rチャンネル" });
  await expect.poll(async () => Number(await left.getAttribute("aria-valuenow"))).toBeGreaterThan(-20);
  await expect.poll(async () => Number(await right.getAttribute("aria-valuenow"))).toBeLessThan(-20);
  await page.getByRole("slider", { name: "マスターボリューム" }).focus();
  await page.keyboard.press("Home");
  await expect.poll(async () => Number(await left.getAttribute("aria-valuenow"))).toBe(-60);
  await expect.poll(async () => Number(await right.getAttribute("aria-valuenow"))).toBe(-60);
});
