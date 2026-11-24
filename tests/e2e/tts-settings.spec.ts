import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test.beforeEach(async ({ page }) => {
  await installMockApi(page, { registeredTts: true });
  await page.goto("/");
  await page.getByRole("button", { name: "設定", exact: true }).click();
});

test("keeps model selection central with a quiet runtime management action", async ({ page }) => {
  const triggers = page.locator(".model-selection-trigger");
  await expect(triggers).toHaveCount(3);
  await expect(triggers.nth(0)).toContainText("Irodori-TTS v4.1 Small");
  await expect(triggers.nth(1)).toContainText("qwen3:8b");
  await expect(triggers.nth(2)).toContainText("Rhubarb");
  await expect(triggers.nth(1)).not.toContainText("oMLX");
  await expect(page.getByRole("button", { name: "oMLX管理" })).toBeVisible();
  const panels = await page.locator(".settings-panel").evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().toJSON()));
  const cards = await triggers.evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().toJSON()));
  expect(panels).toHaveLength(3);
  expect(Math.max(...panels.map(({ y }) => y)) - Math.min(...panels.map(({ y }) => y))).toBeLessThan(1);
  expect(Math.max(...panels.map(({ width }) => width)) - Math.min(...panels.map(({ width }) => width))).toBeLessThan(1);
  expect(Math.max(...panels.map(({ height }) => height)) - Math.min(...panels.map(({ height }) => height))).toBeLessThan(1);
  expect(Math.max(...cards.map(({ y }) => y)) - Math.min(...cards.map(({ y }) => y))).toBeLessThan(1);
  for (const card of cards) expect(card.width / card.height).toBeCloseTo(1.586, 2);
  const [llmTitle, runtimeManagement] = await Promise.all([page.getByRole("heading", { name: "LLM設定" }).boundingBox(), page.getByRole("button", { name: "oMLX管理" }).boundingBox()]);
  expect(runtimeManagement!.x).toBeGreaterThan(llmTitle!.x + llmTitle!.width);
  expect(runtimeManagement!.x - (llmTitle!.x + llmTitle!.width)).toBeLessThan(12);
  expect(runtimeManagement!.height).toBeLessThan(llmTitle!.height);
});

test("fits model selection at the minimum layout width", async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 760 });
  await expect(page.locator(".settings-panel")).toHaveCount(3);
  const panels = await page.locator(".settings-panel").evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().toJSON()));
  expect(panels).toHaveLength(3);
  expect(panels[1].y).toBeGreaterThanOrEqual(panels[0].y + panels[0].height);
  expect(panels[2].y).toBeGreaterThanOrEqual(panels[1].y + panels[1].height);
  for (const box of await page.locator(".model-selection-trigger").evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().toJSON()))) {
    expect(box.x + box.width).toBeLessThanOrEqual(600);
    expect(box.width / box.height).toBeCloseTo(1.586, 2);
  }
  const llmTrigger = page.locator(".model-selection-trigger").nth(1);
  await llmTrigger.hover();
  const popover = page.getByRole("listbox", { name: "LLMモデルの候補" });
  const [triggerBox, popoverBox, optionBox, addBox] = await Promise.all([llmTrigger.boundingBox(), popover.boundingBox(), popover.getByRole("option").boundingBox(), popover.getByRole("button", { name: /\+ 接続先を追加/ }).boundingBox()]);
  expect(popoverBox!.x).toBeGreaterThanOrEqual(0);
  expect(popoverBox!.x + popoverBox!.width).toBeLessThanOrEqual(600);
  expect(optionBox!.width).toBeLessThan(triggerBox!.width);
  expect(optionBox!.width).toBeLessThanOrEqual(240);
  expect(optionBox!.width / optionBox!.height).toBeCloseTo(1.586, 2);
  expect(Math.abs(addBox!.width - optionBox!.width)).toBeLessThan(1);
  expect(addBox!.width / addBox!.height).toBeCloseTo(1.586, 2);
});

test("keeps the last model cards visible while settings refreshes after tab return", async ({ page }) => {
  const triggers = page.locator(".model-selection-trigger");
  await expect(triggers.nth(0)).toContainText("Irodori-TTS v4.1 Small");
  await expect(triggers.nth(1)).toContainText("qwen3:8b");
  await page.getByRole("button", { name: "台本", exact: true }).click();
  for (const path of ["**/api/tts/registry", "**/api/tts/catalog", "**/api/local-llm/runtimes", "**/api/llm/registry"]) {
    await page.route(path, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      await route.fallback();
    });
  }
  await page.getByRole("button", { name: "設定", exact: true }).click();
  await expect(page.getByText(/読み込んでいます…/)).toHaveCount(0);
  await expect(page.locator(".model-selection-trigger").nth(0)).toContainText("Irodori-TTS v4.1 Small");
  await expect(page.locator(".model-selection-trigger").nth(1)).toContainText("qwen3:8b");
});

test("opens an overlay on hover without changing panel layout", async ({ page }) => {
  const trigger = page.locator(".model-selection-trigger").first();
  const before = await page.locator(".settings-panel").first().boundingBox();
  await trigger.hover();
  const popover = page.getByRole("listbox", { name: "音声モデルの候補" });
  await expect(popover).toBeVisible();
  expect((await popover.boundingBox())!.width).toBeGreaterThan(600);
  await expect(popover).toHaveCSS("box-shadow", /rgba?\(/);
  await expect(popover).toHaveCSS("clip-path", "none");
  const option = popover.getByRole("option");
  await expect(option).toHaveCount(3);
  const releaseWidths: number[] = [];
  for (const card of await option.all()) {
    const titleLine = card.locator(".model-card-heading > .tts-model-fit-line");
    const [titleLineBox, titleTextBox] = await Promise.all([titleLine.boundingBox(), titleLine.locator("span").boundingBox()]);
    const cardBox = await card.boundingBox();
    expect(titleLineBox!.width).toBeCloseTo(cardBox!.width - 34, 0);
    expect(titleTextBox!.x + titleTextBox!.width).toBeLessThanOrEqual(titleLineBox!.x + titleLineBox!.width + 0.5);
    expect(titleTextBox!.height).toBeLessThanOrEqual(titleLineBox!.height + 0.5);
    const tagline = card.locator(".tts-model-tagline");
    if (await tagline.count()) {
      const [taglineBox, taglineTextBox] = await Promise.all([tagline.boundingBox(), tagline.locator("span").boundingBox()]);
      expect(taglineTextBox!.x + taglineTextBox!.width).toBeLessThanOrEqual(taglineBox!.x + taglineBox!.width + 0.5);
      expect(taglineTextBox!.height).toBeLessThanOrEqual(taglineBox!.height + 0.5);
    }
    const author = card.locator(".tts-model-author-tag");
    const release = card.locator(".tts-model-release-tag");
    const metadata = card.locator(".tts-model-metadata-tags");
    const [bodyBox, metadataBox, authorBox, authorTagBox, releaseBox] = await Promise.all([card.locator(".model-card-body").boundingBox(), metadata.boundingBox(), author.boundingBox(), author.locator("span").boundingBox(), release.boundingBox()]);
    expect(metadataBox!.width).toBeCloseTo(bodyBox!.width, 0);
    expect(Math.abs(authorBox!.y - releaseBox!.y)).toBeLessThan(1);
    expect(authorTagBox!.x).toBeGreaterThanOrEqual(authorBox!.x + 6);
    expect(authorTagBox!.x + authorTagBox!.width).toBeLessThanOrEqual(authorBox!.x + authorBox!.width - 6);
    releaseWidths.push(releaseBox!.width);
  }
  const animeAuthorScale = await option
    .filter({ hasText: "Small Anime" })
    .locator(".tts-model-author-tag > span")
    .evaluate((element) => Number((element as HTMLElement).style.getPropertyValue("--tts-author-scale")));
  expect(animeAuthorScale).toBe(1);
  expect(Math.max(...releaseWidths) - Math.min(...releaseWidths)).toBeLessThan(1);
  const [triggerBox, optionBox, addBox] = await Promise.all([trigger.boundingBox(), option.first().boundingBox(), popover.getByRole("button", { name: /\+ 音声モデル/ }).boundingBox()]);
  expect(optionBox!.width).toBeLessThan(triggerBox!.width);
  expect(optionBox!.width).toBeLessThanOrEqual(240);
  expect(optionBox!.width / optionBox!.height).toBeCloseTo(1.586, 2);
  expect(Math.abs(addBox!.width - optionBox!.width)).toBeLessThan(1);
  expect(addBox!.width / addBox!.height).toBeCloseTo(1.586, 2);
  await expect(popover.getByRole("button", { name: /\+ 音声モデル/ })).toHaveCSS("opacity", "1");
  await expect(popover.getByRole("button", { name: /\+ ストレージから追加/ })).toHaveCSS("opacity", "1");
  expect((await page.locator(".settings-panel").first().boundingBox())!.height).toBe(before!.height);
});

test("uses the viewport beyond the settings panel for model choices", async ({ page }) => {
  await page.locator(".model-selection-trigger").nth(1).hover();
  const popover = page.getByRole("listbox", { name: "LLMモデルの候補" });
  await expect(popover).toBeVisible();
  const [popoverBox, panelBox] = await Promise.all([popover.boundingBox(), page.locator(".settings-panel").nth(1).boundingBox()]);
  expect(popoverBox!.x + popoverBox!.width).toBeGreaterThan(panelBox!.x + panelBox!.width);
  expect(popoverBox!.x + popoverBox!.width).toBeLessThanOrEqual((page.viewportSize()?.width ?? 0) - 11);
});

test("supports keyboard expansion and opens details from the title-side label", async ({ page }) => {
  const control = page.locator(".model-selection-control").first();
  const trigger = control.locator(".model-selection-trigger");
  await trigger.focus();
  const popover = page.getByRole("listbox", { name: "音声モデルの候補" });
  await trigger.press("ArrowDown");
  await expect(popover.getByRole("option").first()).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(popover).toHaveCount(0);
  await expect(trigger).toBeFocused();
  const details = control.getByRole("button", { name: "音声モデルの詳細" });
  const heading = control.locator(".model-card-heading");
  const [detailsBox, headingBox] = await Promise.all([details.boundingBox(), heading.boundingBox()]);
  expect(detailsBox!.x).toBeGreaterThan(headingBox!.x);
  await details.click();
  await expect(page.getByRole("dialog").getByRole("heading", { name: "Irodori-TTS v4.1 Small" })).toBeVisible();
  await expect(control.locator("button button")).toHaveCount(0);
});

test("keeps existing add flows in the expanded grids", async ({ page }) => {
  await page.locator(".model-selection-trigger").first().click();
  await page
    .getByRole("listbox", { name: "音声モデルの候補" })
    .getByRole("button", { name: /\+ ストレージから追加/ })
    .click();
  await expect(page.getByRole("dialog").getByRole("button", { name: "フォルダを選ぶ" })).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "キャンセル" }).click();
  await page.locator(".model-selection-trigger").nth(1).click();
  await page
    .getByRole("listbox", { name: "LLMモデルの候補" })
    .getByRole("button", { name: /\+ 接続先を追加/ })
    .click();
  await expect(page.getByRole("heading", { name: "接続先からLLMを追加" })).toBeVisible();
});

test("manages unused runtimes without a global selector", async ({ page }) => {
  await installMockApi(page, { registeredTts: true, multipleOmlxRuntimes: true });
  await page.reload();
  await page.getByRole("button", { name: "設定", exact: true }).click();
  await page.getByRole("button", { name: "oMLX管理" }).click();
  const dialog = page.getByRole("dialog", { name: "oMLX管理" });
  await expect(dialog.getByRole("combobox")).toHaveCount(0);
  const optional = dialog.locator("section.llm-detail-section").filter({ hasText: "v0.6.3" });
  await optional.getByRole("button", { name: "実行基盤を削除" }).click();
  await optional.getByRole("button", { name: "もう一度押して削除" }).click();
  await expect(optional).toHaveCount(0);
  await dialog.getByRole("button", { name: "閉じる" }).click();
  await expect(page.locator(".model-selection-trigger").nth(1)).toContainText("qwen3:8b");
});

test("opens the existing TTS download flow", async ({ page }) => {
  await page.locator(".model-selection-trigger").first().click();
  await page
    .getByRole("listbox", { name: "音声モデルの候補" })
    .getByRole("button", { name: /\+ 音声モデル/ })
    .click();
  await expect(page.getByRole("heading", { name: "音声モデルを追加" })).toBeVisible();
  await expect(page.getByText("下記から使用する音声モデルを1つ選んでダウンロードしてください。")).toBeVisible();
  await expect(page.getByText("必要なエンジン、Python環境、Codec、tokenizerもまとめて導入します。")).toHaveCount(0);
  await expect(page.getByText("FP16").first()).toBeVisible();
  const cards = page.locator(".tts-catalog-card");
  await expect(cards).toHaveCount(3);
  await expect(cards.nth(0)).toContainText("Irodori-TTS v4.1 Small");
  await expect(cards.nth(0).getByLabel("作者：Aratako")).toHaveText("Aratako");
  await expect(cards.nth(0).getByLabel("リリース日：2026-08-11")).toHaveText("2026-08-11");
  const [catalogMetadataBox, catalogButtonBox] = await Promise.all([cards.nth(0).locator(".tts-model-metadata-tags").boundingBox(), cards.nth(0).getByRole("button", { name: "追加", exact: true }).boundingBox()]);
  expect(catalogMetadataBox!.x + catalogMetadataBox!.width).toBeLessThanOrEqual(catalogButtonBox!.x);
  expect(catalogButtonBox!.x - (catalogMetadataBox!.x + catalogMetadataBox!.width)).toBeLessThanOrEqual(10);
  await expect(cards.nth(0)).toContainText("音声品質を重視した標準モデルです");
  const variantToggle = cards.nth(0).getByRole("button", { name: "Irodori-TTS v4.1 Smallのバリアントを開く" });
  await expect(variantToggle.locator("svg.double-chevron path")).toHaveCount(2);
  const [cardBox, toggleBox] = await Promise.all([cards.nth(0).boundingBox(), variantToggle.boundingBox()]);
  expect(Math.abs(cardBox!.x + cardBox!.width / 2 - (toggleBox!.x + toggleBox!.width / 2))).toBeLessThanOrEqual(1);
  await variantToggle.click();
  const fp32 = cards.nth(0).getByRole("button", { name: "FP32" });
  const fp16 = cards.nth(0).getByRole("button", { name: "FP16" });
  await expect(cards.nth(0).getByRole("button", { name: "8bit" })).toBeVisible();
  // The locally derived FP32 placeholder is not a download choice, so it is not listed with an explanation.
  await expect(cards.nth(0).locator(".tts-variant-pill")).toHaveCount(3);
  await expect(cards.nth(0)).not.toContainText("公式FP32資産");
  const colors = await cards.nth(0).evaluate((card) => {
    const installed = card.querySelector(".tts-variant-pill.is-installed")!;
    const pending = [...card.querySelectorAll(".tts-variant-pill")].find((item) => item.textContent === "FP16")!;
    return { installed: getComputedStyle(installed).color, pending: getComputedStyle(pending).color };
  });
  expect(colors.installed).not.toBe(colors.pending);
  await expect(fp32).toHaveClass(/is-installed/);
  await expect(fp16).not.toHaveClass(/is-installed/);
  await expect(cards.nth(2)).not.toBeVisible();
  await page.locator(".tts-legacy-models > summary").click();
  await expect(cards.nth(2)).toBeVisible();
  await expect(cards.nth(2)).toContainText("Irodori-TTS v4.1 Small MF");
  await expect(cards.nth(2)).toContainText("生成速度を重視した高速モデルです");
  await expect(cards.nth(1)).toContainText("Irodori-TTS v4.1 Small Anime");
  await expect(cards.nth(1).locator(".tts-third-party-badge")).toHaveCount(0);
  await expect(cards.nth(1).getByLabel("作者：phasefield-audio")).toHaveText("phasefield-audio");
  await expect(cards.nth(1).getByLabel("リリース日：2026-09-04")).toHaveText("2026-09-04");
  await expect(cards.nth(1)).toContainText("アニメ調の音声データで追加学習された第三者モデルです");
  await expect(cards.nth(1)).toContainText("Aratako氏による制作・公式配布ではありません");
  const noticeUsesDangerToken = await cards
    .nth(1)
    .locator(".tts-model-notice")
    .evaluate((element) => {
      const probe = document.createElement("span");
      probe.style.color = "var(--scena-danger)";
      document.body.append(probe);
      const matches = getComputedStyle(element).color === getComputedStyle(probe).color;
      probe.remove();
      return matches;
    });
  expect(noticeUsesDangerToken).toBe(true);
});

test("shows third-party provenance in selection and details", async ({ page }) => {
  await page.locator(".model-selection-trigger").first().click();
  const popover = page.getByRole("listbox", { name: "音声モデルの候補" });
  const anime = popover.getByRole("option").filter({ hasText: "Irodori-TTS v4.1 Small Anime" });
  await expect(anime.locator(".tts-third-party-badge")).toHaveCount(0);
  await expect(anime).not.toContainText("phasefield-audio氏制作の第三者ファインチューニングモデルです");
  await expect(anime).toContainText("アニメ調の音声表現に特化した第三者モデル");
  await anime.click();
  const selectedCard = page.locator(".model-selection-trigger").first();
  const selectedNotice = selectedCard.locator(".tts-selected-model-notice");
  await expect(selectedNotice).toContainText("phasefield-audio氏制作の第三者ファインチューニングモデルです。Aratako氏による制作・公式配布ではありません。");
  const selectedNoticeUsesDangerToken = await selectedNotice.evaluate((element) => {
    const probe = document.createElement("span");
    probe.style.color = "var(--scena-danger)";
    document.body.append(probe);
    const matches = getComputedStyle(element).color === getComputedStyle(probe).color;
    probe.remove();
    return matches;
  });
  expect(selectedNoticeUsesDangerToken).toBe(true);
  const [taglineBox, selectedNoticeBox] = await Promise.all([selectedCard.locator(".tts-model-tagline").boundingBox(), selectedNotice.boundingBox()]);
  expect(selectedNoticeBox!.y - (taglineBox!.y + taglineBox!.height)).toBeGreaterThanOrEqual(8);
  await page.getByRole("button", { name: "音声モデルの詳細" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator(".tts-third-party-badge")).toHaveCount(0);
  await expect(dialog).not.toContainText("モデルの出自");
  await expect(dialog).not.toContainText("phasefield-audio氏制作の第三者ファインチューニングモデルです");
  await expect(dialog).toContainText("アニメ調の音声データで追加学習された第三者モデルです");
  await expect(dialog).toContainText("phasefield-audio");
  await expect(dialog).toContainText("MIT");
  await expect(dialog.getByRole("button", { name: "モデルカード" })).toBeVisible();
});

test("shows exactly two accessible capability pills for supported and unsupported models", async ({ page }) => {
  await page.getByRole("button", { name: "音声モデルの詳細" }).click();
  let dialog = page.getByRole("dialog");
  await expect(dialog.locator(".tts-capabilities li")).toHaveCount(2);
  await expect(dialog.getByRole("listitem", { name: "音声生成：対応" })).toHaveText("音声生成");
  await expect(dialog.getByRole("listitem", { name: "VoiceDesign：対応" })).toHaveText("VoiceDesign");
  await dialog.getByRole("button", { name: "閉じる" }).click();

  await page.locator(".model-selection-trigger").first().click();
  await page.getByRole("listbox", { name: "音声モデルの候補" }).getByRole("option").filter({ hasText: "Irodori-TTS v3 Base" }).click();
  await page.getByRole("button", { name: "音声モデルの詳細" }).click();
  dialog = page.getByRole("dialog");
  await expect(dialog.locator(".tts-capabilities li")).toHaveCount(2);
  await expect(dialog.getByRole("listitem", { name: "音声生成：対応" })).toHaveText("音声生成");
  await expect(dialog.getByRole("listitem", { name: "VoiceDesign：非対応" })).toHaveText("VoiceDesign");
});

test("shows author and release date tags in the installed TTS model body, like the other model cards", async ({ page }) => {
  const card = page.locator(".model-selection-trigger").first();
  const body = card.locator(".model-card-body");
  const metadata = body.locator(".tts-model-metadata-tags");
  await expect(metadata.getByLabel("作者：Aratako")).toHaveText("Aratako");
  await expect(metadata.getByLabel("リリース日：2026-08-11")).toHaveText("2026-08-11");
  await expect(body.locator(".tts-model-metadata-tags")).toHaveCount(1);
  await expect(card.locator(".model-card-heading .tts-model-metadata-tags")).toHaveCount(0);
});

for (const viewport of [
  { width: 1280, height: 900 },
  { width: 1440, height: 960 },
]) {
  test(`keeps the third-party notice usable at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.locator(".model-selection-trigger").first().click();
    await page
      .getByRole("listbox", { name: "音声モデルの候補" })
      .getByRole("button", { name: /\+ 音声モデル/ })
      .click();
    const dialog = page.getByRole("dialog");
    const anime = dialog.locator(".tts-catalog-card").filter({ hasText: "Irodori-TTS v4.1 Small Anime" });
    await expect(anime).toContainText("第三者モデル");
    await expect(anime).not.toContainText("キャプション／絵文字制御は、ベースのv4.1 Smallと異なる場合があります");
    await expect(anime.getByRole("button", { name: "導入済み" })).toBeDisabled();
    await dialog.getByRole("button", { name: "閉じる" }).focus();
    await expect(dialog.getByRole("button", { name: "閉じる" })).toBeFocused();
    const [dialogBox, viewportSize] = await Promise.all([dialog.boundingBox(), page.evaluate(() => ({ width: innerWidth, height: innerHeight }))]);
    expect(dialogBox!.x).toBeGreaterThanOrEqual(0);
    expect(dialogBox!.y).toBeGreaterThanOrEqual(0);
    expect(dialogBox!.x + dialogBox!.width).toBeLessThanOrEqual(viewportSize.width);
    expect(dialogBox!.y + dialogBox!.height).toBeLessThanOrEqual(viewportSize.height);
  });
}
