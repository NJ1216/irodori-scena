import { expect, test, type Page } from "@playwright/test";
import { testToneWav } from "./audio-fixtures";
import { installMockApi } from "./mock-api";

async function expectHeaderOnlyNotice(page: Page, text: string) {
  await expect(page.locator(".notice")).toContainText(text);
  await expect(page.getByRole("status", { name: "通知" })).toBeHidden();
}

async function generateAndPickEmotionCandidates(page: Page) {
  for (const label of ["普通", "喜", "怒", "哀", "楽"]) {
    await page.getByRole("button", { name: `${label}の候補をつくる` }).click();
    await expectHeaderOnlyNotice(page, "声候補を追加しました");
    await page.getByRole("button", { name: `${label}候補 Aを再生` }).click();
  }
}

test.beforeEach(async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");
  await expect(page.getByRole("button", { name: "SCRIPT TITLE 雨上がりの約束" })).toBeVisible();
});

test("edits the script and opens cast controls", async ({ page }) => {
  const line = page.locator(".line-text-editor").first();
  await line.fill("雨上がりの空、きれいだね。");
  await line.blur();
  await expect(line).toHaveText("雨上がりの空、きれいだね。");

  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await page.getByRole("button", { name: "設定を編集" }).first().click();
  await expect(page.getByRole("heading", { name: "キャストの設定を編集" })).toBeVisible();
  await page.getByRole("button", { name: "キャンセル" }).click();
});

test("filters YOUR CAST by cast name", async ({ page }) => {
  await page.getByRole("button", { name: "キャスト", exact: true }).click();

  const savedCharacters = page.locator(".saved-characters");
  const search = savedCharacters.getByRole("searchbox", { name: "キャストを検索" });
  const castNavigation = savedCharacters.getByRole("navigation", { name: "キャストを選択" });
  await expect(search).toBeVisible();

  await search.fill("水瀬");
  await expect(castNavigation.getByRole("button", { name: "水瀬 蓮" })).toBeVisible();
  await expect(castNavigation.getByRole("button", { name: "佐倉 紗良" })).toHaveCount(0);
  await expect(savedCharacters.getByText("1 / 2 人")).toBeVisible();

  await search.fill("該当なし");
  await expect(savedCharacters.getByText("「該当なし」に一致するキャストはいません。")).toBeVisible();

  await search.fill("");
  await expect(castNavigation.getByRole("button", { name: "佐倉 紗良" })).toBeVisible();
  await expect(savedCharacters.getByText("2 人", { exact: true })).toBeVisible();
});

test("drags a cast sticky note into a blank slot and persists its order", async ({ page }) => {
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  const navigation = page.getByRole("navigation", { name: "キャストを選択" });
  const first = navigation.getByRole("button", { name: "佐倉 紗良" });
  const second = navigation.getByRole("button", { name: "水瀬 蓮" });
  const firstBox = await first.boundingBox();
  const secondBox = await second.boundingBox();
  expect(firstBox).not.toBeNull();
  expect(secondBox).not.toBeNull();
  await page.mouse.move(firstBox!.x + firstBox!.width / 2, firstBox!.y + firstBox!.height / 2);
  await page.mouse.down();
  await page.mouse.move(secondBox!.x + secondBox!.width / 2, secondBox!.y + secondBox!.height + 4, { steps: 4 });
  const ghost = page.locator(".cast-notebook-tab-ghost");
  await expect(ghost).toContainText("佐倉 紗良");
  await expect(page.locator(".cast-notebook-tab-slot.is-placeholder")).toHaveCount(1);
  await expect(page.locator(".cast-notebook-drop-line")).toHaveCount(0);
  await page.mouse.up();
  await expect(page.getByText("キャストの順序を保存しました。")).toHaveCount(2);
  await expect(navigation.locator(".cast-notebook-tab-label")).toHaveText(["水瀬 蓮", "佐倉 紗良"]);
  await expect(page.locator(".cast-notebook-spread h2")).toHaveText("佐倉 紗良");
  await page.getByRole("button", { name: "台本", exact: true }).click();
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "キャストを選択" }).locator(".cast-notebook-tab-label")).toHaveText(["水瀬 蓮", "佐倉 紗良"]);
});

test("saves directional cast address and relationship independently", async ({ page }) => {
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await page.getByRole("button", { name: "設定を編集" }).first().click();
  const dialog = page.locator(".character-edit-modal");
  const relationCard = dialog.locator(".cast-relation-card").filter({ hasText: "水瀬 蓮" });
  await expect(dialog.getByLabel("表示名")).toHaveCSS("font-weight", "400");
  await expect(relationCard.getByLabel("関係性")).toHaveCSS("font-weight", "400");
  expect((await relationCard.boundingBox())?.height).toBeLessThan(210);
  await relationCard.getByLabel("呼び方").fill("蓮");
  await relationCard.getByLabel("関係性").fill("幼なじみで、強がりを見抜かれている。");
  await dialog.getByRole("button", { name: "変更を保存" }).click();

  await page.getByRole("button", { name: "設定を編集" }).first().click();
  const reopenedCard = page.locator(".character-edit-modal").locator(".cast-relation-card").filter({ hasText: "水瀬 蓮" });
  await expect(reopenedCard.getByLabel("呼び方")).toHaveValue("蓮");
  await expect(reopenedCard.getByLabel("関係性")).toHaveValue("幼なじみで、強がりを見抜かれている。");
  await page.getByRole("button", { name: "キャンセル" }).click();
  await page.getByRole("navigation", { name: "キャストを選択" }).getByRole("button", { name: "水瀬 蓮" }).click();
  await page.getByRole("button", { name: "設定を編集" }).click();
  const reverseCard = page.locator(".character-edit-modal .cast-relation-card").filter({ hasText: "佐倉 紗良" });
  await expect(reverseCard.getByLabel("呼び方")).toHaveValue("");
  await expect(reverseCard.getByLabel("関係性")).toHaveValue("");
});

test("highlights each AI-suggested cast field until the user edits it", async ({ page }) => {
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await page.getByRole("button", { name: "設定を編集" }).first().click();
  const dialog = page.locator(".character-edit-modal");
  await dialog.getByRole("button", { name: /AIに設定を作ってもらう/ }).click();
  const suggestion = page.locator(".character-profile-suggestion-modal");
  await expect(suggestion.getByRole("radiogroup", { name: "生成方法" })).toContainText("空欄のみ（推奨）すべて");
  await expect(suggestion.getByRole("radiogroup", { name: "生成範囲" })).toContainText("すべて（自由メモ以外）人間関係以外人間関係のみ");
  await page.getByRole("button", { name: "設定を生成" }).click();

  const background = dialog.getByLabel("背景・来歴");
  const relationCard = dialog.locator(".cast-relation-card").filter({ hasText: "水瀬 蓮" });
  const address = relationCard.getByLabel("呼び方");
  const relationship = relationCard.getByLabel("関係性");
  await expect(background).toHaveClass(/ai-suggested-value/);
  await expect(address).toHaveClass(/ai-suggested-value/);
  await expect(relationship).toHaveClass(/ai-suggested-value/);
  await expect(address).toHaveCSS("color", "rgb(57, 125, 115)");
  await expect(address).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  await expect(address).toHaveCSS("box-shadow", "none");
  await expect(dialog.getByText(/緑の項目はAIによる仮入力/)).toBeVisible();

  await address.fill("呼び捨て");
  await expect(address).not.toHaveClass(/ai-suggested-value/);
  await expect(background).toHaveClass(/ai-suggested-value/);
  await expect(relationship).toHaveClass(/ai-suggested-value/);
});

test("shows maintenance guidance in the dialog body", async ({ page }) => {
  await page.locator(".project-menu").hover();
  await page.getByRole("button", { name: "新規作成", exact: true }).click();

  const dialog = page.getByRole("dialog", { name: "新規プロジェクトを作成" });
  const guidance = dialog.getByText("現在の台本を閉じ、新しいプロジェクトを開始します。登録済みのグローバルキャストは引き続き利用できます。");
  await expect(dialog.locator(".dialog-header")).not.toContainText("現在の台本を閉じ");
  await expect(dialog.locator(".dialog-intro")).toContainText("現在の台本を閉じ");
  await expect(guidance).toBeVisible();
  await expect(dialog.locator(".dialog-footer")).toContainText("キャンセル新規作成");
});

test("edits a script-local cast introduction", async ({ page }) => {
  await page.getByRole("button", { name: "台本上の設定を編集" }).first().click();
  const dialog = page.getByRole("dialog", { name: "台本上のキャスト設定" });
  await expect(dialog).toBeVisible();
  await expect(dialog.locator(".dialog-form-fields")).toHaveCSS("display", "grid");
  await expect(page.getByLabel("人物紹介")).toHaveCSS("min-height", "148px");
  await page.getByLabel("役割").fill("配信者（VTuber）");
  await page.getByLabel("人物紹介").fill("明るく率直な配信者。リスナーとの距離が近い。");
  await page.getByRole("button", { name: "保存" }).click();
  const firstSpeakerCard = page.locator(".speaker-card.is-script-cast").first();
  await expect(firstSpeakerCard.locator(".script-cast-role")).toHaveText("配信者（VTuber）");
  await expect(firstSpeakerCard.locator(".script-cast-context")).toHaveText("明るく率直な配信者。リスナーとの距離が近い。");
  const characterName = await page.locator(".speaker-card-primary strong").first().innerText();
  await page.getByRole("button", { name: "台本上の設定を編集" }).first().click();
  await page.getByLabel("役割").fill(characterName);
  await page.getByRole("button", { name: "保存" }).click();
  await expect(firstSpeakerCard.locator(".script-cast-role")).toHaveCount(0);
});

test("saves a complete VoiceDesign reference set", async ({ page }) => {
  const voiceDesignDialog = page.getByRole("dialog", { name: "声の候補をつくる" });
  const setupSection = voiceDesignDialog.locator(".voice-design-setup-step");
  const setupContent = setupSection.locator(".voice-design-setup-content");
  const configure = async () => {
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.getByRole("button", { name: "キャスト", exact: true }).click();
    await page.getByRole("button", { name: /声をつくる/ }).click();
    const [setupStep, setupHeading, auditionStep, auditionHeading] = await Promise.all([
      setupSection.boundingBox(),
      voiceDesignDialog.getByRole("heading", { name: /基準ボイスを選ぶ/ }).boundingBox(),
      voiceDesignDialog.locator(".voice-design-audition-step").boundingBox(),
      voiceDesignDialog.getByRole("heading", { name: /AUDITION/ }).boundingBox(),
    ]);
    expect(Math.abs((setupHeading?.y ?? 0) - (setupStep?.y ?? 0) - ((auditionHeading?.y ?? 0) - (auditionStep?.y ?? 0)))).toBeLessThan(4);
    const setupDisclosure = page.getByRole("button", { name: "基準ボイスの設定を折りたたむ" });
    await expect(setupDisclosure).toHaveCSS("opacity", "0");
    await setupSection.hover();
    await expect(setupDisclosure).toHaveCSS("opacity", "1");
    await setupDisclosure.click();
    await expect(setupContent).toHaveCSS("opacity", "0");
    await expect(setupContent).toHaveAttribute("inert", "");
    await expect.poll(async () => (await setupContent.boundingBox())?.height ?? 0).toBeLessThanOrEqual(2);
    await page.getByRole("button", { name: "基準ボイスの設定を展開" }).click();
    await page.getByRole("button", { name: "基準用の試聴台詞のヒント" }).hover();
    await expect(page.getByRole("tooltip")).toContainText("実際にそのキャストが話しているような口調の台詞");
    await page.getByRole("button", { name: "年齢" }).click();
    await page.getByRole("option", { name: "20代" }).click();
    await page.getByRole("button", { name: "声質" }).click();
    await page.getByRole("checkbox", { name: "太い" }).check();
    await page.keyboard.press("Escape");
    await page.getByRole("textbox", { name: "追加要望・備考" }).fill("明るく穏やかな声");
    const [candidateActionsBeforeGeneration, candidateCountBeforeGeneration] = await Promise.all([page.getByRole("group", { name: "基準ボイスの候補操作" }).boundingBox(), page.getByLabel("候補数").boundingBox()]);
    expect(candidateActionsBeforeGeneration?.height).toBe(candidateCountBeforeGeneration?.height);
    await expect(voiceDesignDialog.locator(".voice-design-audition-step > .audition-list")).toHaveCSS("border-top-style", "solid");
  };
  const generate = async () => {
    await page.route(
      "**/api/characters/candidates",
      async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 400));
        await route.fallback();
      },
      { times: 1 },
    );
    await page.getByRole("button", { name: "基準ボイス候補をつくる" }).click();
    const generatingChoices = voiceDesignDialog.locator(".voice-candidate-choices.is-generating");
    await expect(generatingChoices).toHaveAttribute("aria-busy", "true");
    await expect(generatingChoices.getByRole("button")).toHaveCount(3);
    await expect(generatingChoices.getByRole("button").first()).toBeDisabled();
    await expect(generatingChoices.getByRole("button").first()).toHaveCSS("animation-name", "voice-candidate-generating");
    await expect(generatingChoices.locator(".voice-candidate-generating-border").first()).toHaveCSS("animation-name", "voice-candidate-border-flow");
    await expect(setupContent).toHaveCSS("opacity", "0");
    await expect.poll(async () => (await setupContent.boundingBox())?.height ?? 0).toBeLessThanOrEqual(2);
  };
  const inspectGenerated = async () => {
    await expectHeaderOnlyNotice(page, "声候補を追加しました");
    await expect(page.getByRole("heading", { name: /AUDITION/ })).toBeVisible();
    const consultAgain = page.getByRole("button", { name: "再びAIに声の設計を相談" });
    await expect(consultAgain).toBeVisible();
    await expect(consultAgain).toBeEnabled();
    const [collapsedHeadingBox, disclosureBox] = await Promise.all([voiceDesignDialog.getByRole("heading", { name: /基準ボイスを選ぶ/ }).boundingBox(), page.getByRole("button", { name: "基準ボイスの設定を展開" }).boundingBox()]);
    expect(disclosureBox?.height).toBeLessThanOrEqual(collapsedHeadingBox?.height ?? 0);
    await expect(page.getByRole("button", { name: "基準候補 Aを再生" })).toBeVisible();
    const [candidateActions, candidateCount] = await Promise.all([page.getByRole("group", { name: "基準ボイスの候補操作" }).boundingBox(), page.getByLabel("候補数").boundingBox()]);
    expect(Math.abs((candidateActions?.y ?? 0) - (candidateCount?.y ?? 0))).toBeLessThan(32);
    expect((candidateCount?.x ?? 0) - ((candidateActions?.x ?? 0) + (candidateActions?.width ?? 0))).toBeLessThan(16);
    await expect(page.getByLabel("候補数")).toHaveCSS("appearance", "none");
    await expect(voiceDesignDialog.getByText("準備できました。キャストを登録して、台本を書き始めましょう。")).toHaveCount(0);
    await setupSection.hover();
    await page.getByRole("button", { name: "基準ボイスの設定を展開" }).click();
    await expect(page.getByRole("textbox", { name: "追加要望・備考" })).toBeVisible();
    await page.getByRole("button", { name: "基準ボイスの設定を折りたたむ" }).click();
    await expect(setupContent).toHaveCSS("opacity", "0");
    await expect.poll(async () => (await setupContent.boundingBox())?.height ?? 0).toBeLessThanOrEqual(2);
  };
  const save = async () => {
    await page.getByRole("button", { name: "基準候補 Aを再生" }).click();
    const castName = page.getByLabel("キャスト名");
    await expect(castName).toHaveValue("新規キャスト");
    await castName.fill("");
    await expect(castName).toHaveAttribute("aria-invalid", "true");
    await expect(castName).toHaveCSS("background-color", "rgb(255, 244, 247)");
    await expect(castName).toHaveCSS("border-color", "rgb(183, 92, 120)");
    await page.getByRole("button", { name: "参照ボイスを保存" }).click();
    await expect(castName.locator("xpath=..").getByRole("alert")).toHaveText("キャスト名は必須です。");
    await expect(castName).toBeFocused();
    await expect(page.getByRole("status", { name: "通知" })).toBeHidden();
    await castName.fill("入力済みの名前");
    await expect(voiceDesignDialog.getByText("キャスト名は必須です。")).toHaveCount(0);
    await page.getByRole("button", { name: /基準候補 Aを/ }).click();
    await expect(castName).toHaveValue("入力済みの名前");
    await expect(castName).toHaveAttribute("aria-invalid", "false");
    const emotionOption = voiceDesignDialog.locator(".voice-design-audition-step .voice-design-emotion-option");
    await expect(emotionOption).toBeVisible();
    await expect(emotionOption).toHaveCSS("border-top-style", "solid");
    await expect(emotionOption.locator(".voice-design-emotion-toggle")).toHaveCSS("border-top-width", "0px");
    const saveHeading = voiceDesignDialog.getByRole("heading", { name: /キャストとして保存/ });
    await expect(saveHeading.locator("span")).toHaveText("3");
    await page.getByLabel("感情参照を追加する（任意）").check();
    await expect(page.locator(".voice-design-workspace")).toHaveClass(/has-emotions/);
    await expect(voiceDesignDialog.getByRole("heading", { name: /感情を追加/ }).locator("span")).toHaveText("3");
    await expect(saveHeading.locator("span")).toHaveText("4");
    await expect.poll(async () => page.locator(".voice-design-emotions").boundingBox()).toMatchObject({ x: expect.any(Number) });
    const [baselineBox, emotionsBox] = await Promise.all([page.locator(".voice-design-baseline-panel").boundingBox(), page.locator(".voice-design-emotions").boundingBox()]);
    expect(emotionsBox?.x).toBeGreaterThan(baselineBox?.x ?? 0);
    await expect(page.locator(".voice-emotion textarea").first()).toHaveCSS("height", "58px");
    await generateAndPickEmotionCandidates(page);
    await castName.fill("新しい声");
    await page.getByRole("button", { name: "参照ボイスを保存" }).click();

    await expect(page.getByRole("button", { name: "キャスト", exact: true })).toHaveClass(/active/);
    await expect(page.getByRole("dialog", { name: "声の候補をつくる" })).toBeHidden();
    await expect(page.getByRole("navigation", { name: "キャストを選択" }).getByRole("button", { name: "新しい声" })).toBeVisible();
  };
  await configure();
  await generate();
  await inspectGenerated();
  await save();
});

test("starts a new VoiceDesign with empty structured input", async ({ page }) => {
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await page.getByRole("button", { name: /声をつくる/ }).click();
  const keywords = page.getByRole("textbox", { name: "追加要望・備考" });
  await keywords.fill("静かで芯のある声");
  await page.getByRole("button", { name: "キャンセル" }).click();
  await page.getByRole("button", { name: /声をつくる/ }).click();
  await expect(page.getByRole("textbox", { name: "追加要望・備考" })).toHaveValue("");
});

test("keeps VoiceDesign setup open when audition validation fails", async ({ page }) => {
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await page.getByRole("button", { name: /声をつくる/ }).click();
  await page.getByRole("button", { name: "基準ボイス候補をつくる" }).click();

  await expect(page.getByRole("textbox", { name: "追加要望・備考" })).toBeVisible();
  await expect(page.getByRole("button", { name: "基準ボイスの設定を折りたたむ" })).toBeAttached();
  const footerError = page.getByRole("dialog", { name: "声の候補をつくる" }).locator(".dialog-footer").getByRole("alert");
  await expect(footerError).toHaveText("声の条件を1項目以上入力してください。");
  await expect(page.getByRole("status", { name: "通知" })).toBeHidden();
  await page.getByRole("textbox", { name: "追加要望・備考" }).fill("明るい声");
  await expect(footerError).toHaveCount(0);
});

test("shows a missing audition line under its field and focuses it", async ({ page }) => {
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await page.getByRole("button", { name: /声をつくる/ }).click();
  await page.getByRole("textbox", { name: "追加要望・備考" }).fill("明るい声");
  const sample = page.getByRole("textbox", { name: "基準用の試聴台詞" });
  await sample.fill("");
  await page.getByRole("button", { name: "基準ボイス候補をつくる" }).click();
  await expect(sample).toBeFocused();
  await expect(sample).toHaveAttribute("aria-invalid", "true");
  await expect(sample.locator("xpath=..").getByRole("alert")).toHaveText("候補を聞き比べるサンプル台詞を入力してください。");
  await expect(page.getByRole("status", { name: "通知" })).toBeHidden();
  await sample.fill("こんにちは。");
  await expect(page.getByText("候補を聞き比べるサンプル台詞を入力してください。")).toHaveCount(0);
});

test("keeps dialog header and footer fixed while its body scrolls", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await page.getByRole("button", { name: /声をつくる/ }).click();

  const dialog = page.getByRole("dialog", { name: "声の候補をつくる" });
  const header = dialog.locator(".dialog-header");
  const footer = dialog.locator(".dialog-footer");
  const before = await Promise.all([header.boundingBox(), footer.boundingBox()]);
  await expect(header).toHaveCSS("border-bottom-width", "0px");
  await expect(footer).toHaveCSS("border-top-width", "0px");
  await expect(header).toHaveCSS("background-color", "color(srgb 1 1 1 / 0.86)");
  await expect(footer).toHaveCSS("background-color", "color(srgb 1 1 1 / 0.86)");
  await expect(header).toHaveCSS("backdrop-filter", "blur(16px) saturate(1.08)");
  await expect(footer).toHaveCSS("backdrop-filter", "blur(16px) saturate(1.08)");
  await dialog.evaluate((element) => {
    element.scrollTop = 360;
    element.dispatchEvent(new Event("scroll"));
  });
  await expect.poll(() => dialog.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  const scrollbar = page.getByRole("scrollbar", { name: "ダイアログ" });
  await expect(scrollbar).toBeVisible();
  const bar = await scrollbar.locator("..").boundingBox();
  expect(Math.round(bar!.y)).toBe(Math.round(before[0]!.y + before[0]!.height));
  expect(Math.round(bar!.y + bar!.height)).toBe(Math.round(before[1]!.y));
  const after = await Promise.all([header.boundingBox(), footer.boundingBox()]);

  expect(Math.round(after[0]!.y)).toBe(Math.round(before[0]!.y));
  expect(Math.round(after[1]!.y)).toBe(Math.round(before[1]!.y));
});

test("moves and batch-selects lines with the keyboard", async ({ page }) => {
  await page.locator('[data-line-id="line-1"]').click();
  await page.keyboard.press("ArrowDown");
  await expect(page.locator('[data-line-id="line-2"]')).toHaveClass(/is-selected/);
  await page.keyboard.press("Shift+ArrowUp");
  const selectedLines = page.locator(".line-card.is-selected");
  await expect(selectedLines).toHaveCount(2);
  expect(
    await selectedLines.evaluateAll((lines) =>
      lines.every((line) => {
        const style = getComputedStyle(line);
        return style.borderTopColor === "rgb(120, 168, 212)" && style.outlineColor === "rgb(0, 95, 204)" && style.outlineStyle === "solid" && style.outlineWidth === "1px" && style.boxShadow === "none";
      }),
    ),
  ).toBe(true);
  await page.keyboard.press("Meta+a");
  await expect(page.locator(".line-card.is-selected")).toHaveCount(2);
  await page.keyboard.press("Meta+Alt+r");
  await expect(page.locator(".line-card.generated")).toHaveCount(2);
});

test("continuous playback uses only the playback animation", async ({ page }) => {
  await page.route("**/api/media/takes/line-1.wav", (route) => route.fulfill({ body: testToneWav(5), contentType: "audio/wav" }));
  const firstLine = page.locator('[data-line-id="line-1"]');
  await firstLine.locator(".generate").click();
  await expect(firstLine).toHaveClass(/generated/);
  const ordinarySelectionStyle = await firstLine.evaluate((line) => {
    const style = getComputedStyle(line);
    return {
      borderColor: style.borderColor,
      backgroundColor: style.backgroundColor,
    };
  });
  await page.getByRole("button", { name: "▶ 連続再生" }).click();
  await expect(firstLine).toHaveClass(/is-playing/);
  await expect(firstLine).toHaveClass(/is-focused/);
  await expect(firstLine).toHaveClass(/is-selected/);
  // The pulse runs on a pre-painted ::before layer (opacity only), never on the card itself.
  await expect(firstLine).toHaveCSS("animation-name", "none");
  await expect.poll(() => firstLine.evaluate((line) => getComputedStyle(line, "::before").animationName)).toBe("scena-line-pulse");
  await expect(firstLine.locator(".line-number")).toHaveCSS("animation-name", "none");
  await expect(firstLine).toHaveCSS("border-color", ordinarySelectionStyle.borderColor);
  await expect(firstLine).toHaveCSS("background-color", ordinarySelectionStyle.backgroundColor);
  await page.getByRole("button", { name: "■ 停止" }).click();
});

test("automatic generation preserves siblings and retries only the failed line", async ({ page }) => {
  let firstLineRequests = 0;
  let secondLineRequests = 0;
  const failedNotices: string[] = [];
  await page.exposeFunction("recordGenerationNotice", (message: string) => failedNotices.push(message));
  await page.evaluate(() => {
    const notice = document.querySelector(".notice")!;
    new MutationObserver(() => {
      void (window as typeof window & { recordGenerationNotice: (message: string) => Promise<void> }).recordGenerationNotice(notice.querySelector(".notice-screen-reader-text")?.textContent ?? "");
    }).observe(notice, { childList: true, subtree: true, characterData: true });
  });
  await page.route("**/api/lines/line-1/generate", async (route) => {
    firstLineRequests += 1;
    if (firstLineRequests === 1) {
      await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: { code: "render_input_changed", message: "生成中に発話の内容が変更されました。" } }) });
      return;
    }
    await route.fallback();
  });
  await page.route("**/api/lines/line-2/generate", async (route) => {
    secondLineRequests += 1;
    await route.fallback();
  });
  const toggle = page.getByRole("button", { name: "自動生成" });
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await toggle.click();
  await expect.poll(() => firstLineRequests).toBe(1);
  await expect.poll(() => secondLineRequests).toBe(1);
  await expect.poll(() => failedNotices.some((message) => message.includes("この生成要求を完了できませんでした: 生成中に発話の内容が変更されました。"))).toBe(true);
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator('[data-line-id="line-1"]')).not.toHaveClass(/generated/);
  await expect(page.locator('[data-line-id="line-2"]')).toHaveClass(/generated/);
  await toggle.click();
  await toggle.click();
  await expect.poll(() => firstLineRequests).toBe(2);
  expect(secondLineRequests).toBe(1);
  await expect(page.locator(".line-card.generated")).toHaveCount(2);
});

test("uses the same ordered selection for R and P generation shortcuts", async ({ page }) => {
  const generationRequests: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/api\/lines\/line-[12]\/(generate|regenerate)$/.test(new URL(request.url()).pathname)) {
      generationRequests.push(new URL(request.url()).pathname);
    }
  });
  await page.route("**/api/media/takes/**", (route) => route.fulfill({ body: testToneWav(5), contentType: "audio/wav" }));
  await page.route("**/api/lines/line-1/generate", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 100));
    await route.fallback();
  });
  await page.locator('[data-line-id="line-1"]').click();
  await page.keyboard.press("Meta+Alt+p");
  await expect(page.locator('[data-line-id="line-1"]')).toHaveClass(/is-generating/);
  await expect(page.locator('[data-line-id="line-1"]')).toHaveClass(/generated/);
  await expect(page.locator('[data-line-id="line-2"]')).not.toHaveClass(/generated/);
  await expect(page.getByRole("button", { name: "1行の再生を停止" })).toBeVisible();
  await page.keyboard.press("Space");
  await expect(page.getByRole("button", { name: "1行を台本順に再生" })).toBeVisible();
  await expect(page.getByRole("button", { name: "生成をキャンセル" })).toBeHidden();
  await page.keyboard.press("Meta+Shift+p");
  await expect.poll(() => generationRequests).toContain("/api/lines/line-1/regenerate");
  await page.keyboard.press("Space");
  await expect(page.getByRole("button", { name: "生成をキャンセル" })).toBeHidden();
  await page.locator('[data-line-id="line-1"]').click();
  await page.keyboard.press("Shift+ArrowDown");
  await page.keyboard.press("Meta+Alt+p");
  await expect.poll(() => generationRequests).toContain("/api/lines/line-2/generate");
  await expect(page.locator('[data-line-id="line-2"]')).not.toHaveClass(/is-generating/);
  await page.getByRole("button", { name: "生成をキャンセル" }).click();
  await expect(page.getByRole("button", { name: "生成をキャンセル" })).toBeHidden();
  await expect(page.getByRole("status")).toContainText("選択行の生成をキャンセルしました");
  const requestCount = generationRequests.length;
  await page.keyboard.press("Meta+Alt+r");
  await expect.poll(() => generationRequests.length).toBeGreaterThan(requestCount);
  await expect(page.getByRole("status")).toContainText("2 行を新規生成しました");
  const regenerationCount = generationRequests.filter((path) => path.endsWith("/regenerate")).length;
  await page.keyboard.press("Meta+Shift+r");
  await expect.poll(() => generationRequests.filter((path) => path.endsWith("/regenerate")).length).toBe(regenerationCount + 2);
  const shortcuts = page.locator("section.shortcut-card");
  await expect(shortcuts).toContainText("⌘⇧P");
  await expect(shortcuts).toContainText("⌘⌥P");
  await expect(shortcuts).toContainText("⌘⌥R");
  await expect(shortcuts).toContainText("⌘Enter");
  await expect(shortcuts).toContainText("カーソル位置で発話行を分割");
});
