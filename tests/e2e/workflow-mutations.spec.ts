import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test.beforeEach(async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");
  await expect(page.getByRole("button", { name: "SCRIPT TITLE 雨上がりの約束" })).toBeVisible();
});

test("deletes all selected lines with Delete", async ({ page }) => {
  await page.locator('[data-line-id="line-1"]').click();
  await page.keyboard.press("Shift+ArrowDown");
  await page.keyboard.press("Delete");
  await expect(page.locator(".notice")).toContainText("4秒以内にもう一度実行");
  await expect(page.locator(".line-card.is-selected .delete-line.is-confirming")).toHaveCount(2);
  await expect(page.locator(".line-card.is-confirming")).toHaveCount(0);
  await expect(page.locator(".delete-line.is-confirming").first()).toHaveCSS("animation-name", "scena-confirmation-attention");
  await page.keyboard.press("Delete");
  const canvases = page.locator(".script-deletion-canvas");
  // One composited canvas now renders both deleted rows.
  await expect(canvases).toHaveCount(1);
  const renderedRows = await page.evaluate(() => window.__SCENA_PARTICLE_DELETION_DIAGNOSTICS__?.read().find((entry) => entry.target === "line" && entry.phase === "mounted")?.count);
  expect(renderedRows).toBe(2);
  const firstFrame = await canvases.first().evaluate((element) => (element as HTMLCanvasElement).toDataURL());
  await page.waitForTimeout(350);
  expect(await canvases.first().evaluate((element) => (element as HTMLCanvasElement).toDataURL())).not.toBe(firstFrame);
  await expect(page.locator(".line-card")).toHaveCount(0);
  const emptySceneAppend = page.locator(".scene-box .line-insert-zone.is-append");
  await expect(emptySceneAppend.getByRole("button", { name: "発話行を追加", exact: true })).toBeVisible();
  await expect(emptySceneAppend.locator(".line-insert-actions")).toHaveCSS("opacity", "0");
});

test("deletes all selected lines from a selected row's trash button", async ({ page }) => {
  await page.locator('[data-line-id="line-1"]').click();
  await page.keyboard.press("Shift+ArrowDown");
  const selected = page.locator(".line-card.is-selected");
  await expect(selected).toHaveCount(2);
  const trash = selected.first().locator(".delete-line");
  await trash.click();
  await expect(selected).toHaveCount(2);
  await expect(page.locator(".notice")).toContainText("4秒以内にもう一度実行");
  await trash.click();
  await expect(page.locator(".line-card")).toHaveCount(0);
});

test("runs new-take and overwrite buttons for every selected line", async ({ page }) => {
  await page.unroute("**/api/**");
  await installMockApi(page, { generatedTake: true, lineCount: 2 });
  await page.reload();
  const requests: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/api\/lines\/line-[12]\/(generate|regenerate)$/.test(new URL(request.url()).pathname)) requests.push(new URL(request.url()).pathname);
  });
  const cards = page.locator(".line-card");
  await cards.first().locator(".line-main").click();
  await cards
    .last()
    .locator(".line-main")
    .click({ modifiers: ["Shift"] });
  await expect(page.locator(".line-card.is-selected")).toHaveCount(2);
  await cards.first().locator(".generate").click();
  await expect(page.locator(".line-card.is-selected")).toHaveCount(2);
  await expect.poll(() => requests.filter((path) => path.endsWith("/generate")).length).toBe(2);
  await cards.first().hover();
  await cards.first().locator(".regenerate-hover").click();
  await expect(page.locator(".line-card.is-selected")).toHaveCount(2);
  await expect.poll(() => requests.filter((path) => path.endsWith("/regenerate")).length).toBe(2);
});

test("draws attention to a destructive button awaiting confirmation", async ({ page }) => {
  const line = page.locator('[data-line-id="line-1"]');
  const deleteLine = line.locator(".delete-line");
  await line.hover();
  await deleteLine.click();
  await expect(deleteLine).toHaveClass(/is-confirming/);
  await expect(deleteLine).toHaveCSS("animation-name", "scena-confirmation-attention");
  await expect(line.locator(".line-transient-actions")).toHaveCSS("overflow", "visible");
  await expect(page.locator(".notice")).toContainText("4秒以内にもう一度実行");
  await deleteLine.click();
  await expect(page.locator('[data-line-id="line-1"]')).toHaveCount(0);
});

test("deletes a scene through the in-app confirmation", async ({ page }) => {
  const sceneHeader = page.locator(".scene-header");
  await sceneHeader.hover();
  await page.getByRole("button", { name: "シーン全体を削除" }).click();
  await expect(page.getByRole("button", { name: "もう一度押してシーンを削除" })).toBeVisible();
  await expect(page.getByRole("button", { name: "もう一度押してシーンを削除" })).toHaveCSS("animation-name", "scena-confirmation-attention");
  await page.getByRole("button", { name: "もう一度押してシーンを削除" }).click();
  await expect(page.locator(".scene-box")).toHaveCount(0);
  await expect(page.locator(".notice")).toContainText("駅前」を削除しました");

  const emptySceneZone = page.locator(".empty-scene-zone");
  await emptySceneZone.dispatchEvent("mouseover");
  await expect(emptySceneZone).toHaveClass(/is-revealed/, { timeout: 250 });
  await page.getByRole("button", { name: "＋ シーンと発話行を追加" }).click();
  await expect(page.locator(".scene-box")).toHaveCount(1);
  await expect(page.locator(".line-card")).toHaveCount(1);
  await expect(page.locator(".line-text-editor")).toBeFocused();
  await expect(page.locator(".notice")).toContainText("シーンと発話行を追加しました");
});
test("previews an insertion position before revealing its actions", async ({ page }) => {
  const insertZone = page.locator(".line-insert-zone").first();
  const appendZone = page.locator(".line-insert-zone.is-append").last();
  const appendMarker = appendZone.getByRole("button", { name: "発話行を追加", exact: true });
  await expect(appendMarker).toBeVisible();
  await expect(appendZone.locator(".line-insert-actions")).toHaveCSS("opacity", "0");
  const [appendZoneBox, appendButtonBox] = await Promise.all([appendZone.boundingBox(), appendMarker.boundingBox()]);
  const appendZoneCenter = (appendZoneBox?.y ?? 0) + (appendZoneBox?.height ?? 0) / 2;
  const appendButtonCenter = (appendButtonBox?.y ?? 0) + (appendButtonBox?.height ?? 0) / 2;
  expect(Math.abs(appendZoneCenter - appendButtonCenter)).toBeLessThan(1);
  await appendZone.hover();
  await expect(appendZone).toHaveClass(/is-revealed/);
  await expect(appendMarker).toHaveCount(0);
  await expect(appendZone.locator(".line-insert-actions")).toHaveCSS("opacity", "1");
  await expect(insertZone.locator(".line-insert-actions")).toHaveCSS("opacity", "0");
  await insertZone.hover();
  await expect(insertZone).not.toHaveClass(/is-revealed/);
  await expect(insertZone).toHaveCSS("height", "9px");
  const preview = await insertZone.evaluate((element) => {
    const style = getComputedStyle(element, "::after");
    return [style.borderTopStyle, style.opacity];
  });
  expect(preview).toEqual(["dotted", "1"]);
  await expect(insertZone).toHaveClass(/is-revealed/);
  expect(await insertZone.evaluate((element) => getComputedStyle(element, "::after").opacity)).toBe("0");
  await expect(insertZone.getByRole("button", { name: "発話行を挿入" })).toBeVisible();
});
test("resets scene deletion confirmation after a short delay", async ({ page }) => {
  await page.locator(".scene-header").hover();
  await page.getByRole("button", { name: "シーン全体を削除" }).click();
  await expect(page.getByRole("button", { name: "もう一度押してシーンを削除" })).toBeVisible();
  await page.waitForTimeout(4_100);
  await expect(page.getByRole("button", { name: "シーン全体を削除" })).toBeVisible();
});

test("clicking the script title card opens its editor", async ({ page }) => {
  await page.locator(".script-title-editor").click({ position: { x: 18, y: 52 } });

  await expect(page.getByLabel("台本タイトル")).toBeFocused();
});

test("imports pasted dialogue after assigning its speakers", async ({ page }) => {
  await page.getByRole("button", { name: "プロジェクト" }).hover();
  await page.getByRole("button", { name: "台本読み込み" }).click();
  await page.getByLabel("台本データ").fill("佐倉:こんにちは。\n水瀬|やあ。");
  await expect(page.getByRole("heading", { name: "台本上の名前とキャストを紐付け" })).toBeVisible();
  await page.getByRole("button", { name: "台本に読み込む" }).click();
  await expect(page.locator(".notice")).toContainText("2行を台本に読み込みました");
  await expect(page.locator(".line-text-editor")).toHaveCount(4);
});

test("uses registered LLM models instead of legacy connection settings", async ({ page }) => {
  await page.getByRole("button", { name: "設定", exact: true }).click();
  await expect(page.getByRole("heading", { name: "LLM設定" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "LLMの既定接続" })).toHaveCount(0);
  const llmTrigger = page
      .locator(".settings-panel")
      .filter({ has: page.getByRole("heading", { name: "LLM設定", exact: true }) })
      .locator(".model-selection-trigger"),
    llmPopover = page.getByRole("listbox", { name: "LLMモデルの候補" });
  await expect(llmTrigger).toContainText("qwen3:8b");
  await expect(page.getByRole("button", { name: /接続先を追加/ })).toHaveCount(0);
  await llmTrigger.click();
  const hiddenLlmAdd = llmPopover.getByRole("button", { name: /接続先を追加/ });
  await expect(hiddenLlmAdd).toHaveCSS("opacity", "1");
  await expect(llmPopover.getByRole("button", { name: /SCENA内蔵LLMにモデルを追加/ })).toHaveCSS("opacity", "1");
  await expect(page.locator(".llm-board .llm-status-indicator")).toHaveCount(0);
  await expect(page.locator(".llm-endpoint-section, .llm-endpoint-add, .huggingface-search")).toHaveCount(0);
  await hiddenLlmAdd.click();
  await expect(page.getByLabel("種類").locator("option[value='scena-local']")).toHaveCount(0);
  await expect(page.getByLabel("URL")).toHaveValue("http://127.0.0.1:11434/v1");
  await page.getByLabel("種類").selectOption("lmstudio");
  await expect(page.getByLabel("URL")).toHaveValue("http://127.0.0.1:1234/v1");
  await expect(page.getByLabel("API Key", { exact: true })).toHaveCount(0);
  await page.getByRole("checkbox", { name: "API Keyを設定（任意）" }).check();
  const apiKey = page.getByRole("textbox", { name: /^API Key/ });
  await expect(apiKey).toBeVisible();
  await apiKey.fill("test-key");
  await page.getByRole("button", { name: "モデルを確認" }).click();
  const model = page.getByRole("combobox", { name: /^モデル/ });
  await expect(model).toHaveValue("qwen3:8b");
  await page.getByRole("button", { name: "モデル候補を表示" }).click();
  const modelMenu = page.getByRole("listbox");
  await expect(modelMenu).toBeVisible();
  await expect(modelMenu).toHaveCSS("background-color", "rgb(255, 255, 255)");
  await expect(modelMenu.getByRole("option")).toHaveText(["qwen3:8b", "gemma3:12b"]);
  await modelMenu.getByRole("option", { name: "gemma3:12b" }).click();
  await expect(model).toHaveValue("gemma3:12b");
  await expect(page.getByRole("button", { name: "このモデルを追加" })).toBeEnabled();
  await model.fill("gpt-oss:120b-cloud");
  await expect(page.getByRole("button", { name: "このモデルを追加" })).toBeEnabled();
  await expect(page.getByLabel("検索")).toHaveCount(0);
  await page.getByRole("button", { name: "キャンセル" }).click();
  await llmTrigger.click();
  await page
    .getByRole("listbox", { name: "LLMモデルの候補" })
    .getByRole("button", { name: /SCENA内蔵LLMにモデルを追加/ })
    .click();
  await expect(page.getByText("モデルは1つずつ追加します。")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Hugging Faceから探す/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Mac内のフォルダから選ぶ/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "LLMモデルの詳細" }).click();
  const dialog = page.getByRole("dialog");
  const defaultLlm = dialog.getByRole("button", { name: "既定のLLM" });
  await expect(defaultLlm).toBeDisabled();
  await expect(defaultLlm).toHaveCSS("color", "rgb(57, 125, 115)");
  await expect(defaultLlm).toHaveCSS("border-radius", "16px");
  await expect(dialog.getByLabel("表示名")).toHaveValue("qwen3:8b");
  await expect(dialog.getByText("qwen3:8b (Ollama)", { exact: true })).toBeVisible();
  await expect(dialog.getByText("http://127.0.0.1:11434/v1", { exact: true })).toBeVisible();
  await expect(dialog.getByLabel("接続先URL")).toHaveCount(0);
  await expect(dialog.getByLabel("API Key")).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "モデル情報を保存" })).toHaveCount(0);
  await expect(dialog.locator(".llm-status-indicator")).toHaveCount(0);
  await expect(dialog.getByText("接続でき、モデルの使用に問題がないことを確認しました。", { exact: true })).toBeVisible();
  await expect(dialog.getByText("Ollama・基本動作確認済み")).toHaveCount(0);
  await dialog.getByRole("button", { name: "基本動作を確認" }).click();
  await expect(dialog.getByRole("button", { name: "確認を取り消す" })).toBeEnabled();
  await expect(dialog.getByRole("button", { name: "キャンセル" })).toHaveCount(0);
  await expect(dialog.getByText("接続でき、モデルの使用に問題がないことを確認しました。", { exact: true })).toBeVisible();
  await dialog.getByLabel("表示名").fill("執筆用 qwen");
  await page.getByText("高度な設定").click();
  await expect(page.getByLabel("Temperature")).toHaveAttribute("placeholder", "機能の既定値");
  await expect(page.getByLabel("Top-p")).toBeVisible();
  await expect(page.getByLabel("Top-k")).toBeVisible();
  await expect(page.getByText("trust_remote_code")).toHaveCount(0);
  await expect(page.getByText("SCENAへの登録だけを解除します。接続先サーバーのモデルは削除しません。")).toHaveCount(0);
  await page.getByLabel("Temperature").fill("0.4");
  const saved = page.waitForRequest((request) => request.url().endsWith("/api/llm/cards/card-e2e") && request.method() === "PATCH");
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  const request = await saved;
  expect(request.postDataJSON()).toMatchObject({ displayName: "執筆用 qwen", settings: { temperature: 0.4 } });
  await expect(dialog).toHaveCount(0);
  await page.getByRole("button", { name: "LLMモデルの詳細" }).click();
  const closeBox = await page.getByRole("button", { name: "閉じる" }).boundingBox();
  const removalBox = await page.getByRole("button", { name: "登録を解除" }).boundingBox();
  expect(removalBox!.x).toBeLessThan(closeBox!.x);
  await page.getByRole("button", { name: "登録を解除" }).click();
  const unregister = page.getByRole("button", { name: "もう一度押して登録を解除" });
  await expect(unregister).toHaveClass(/is-confirming/);
  await expect(unregister).toHaveCSS("animation-name", "scena-confirmation-attention");
  const confirmation = page.getByText(/4秒以内にもう一度実行すると登録解除します/);
  await expect(confirmation).toBeVisible();
  await expect(confirmation).toHaveCSS("font-size", "12px");
  await expect(confirmation).toHaveCSS("color", "rgb(168, 123, 54)");
});

test("starts and cancels an AI draft", async ({ page }) => {
  await page.getByRole("button", { name: "AI台本" }).click();
  await page.getByRole("button", { name: /佐倉 紗良/ }).click();
  await page.getByLabel("テーマ／状況").fill("雨上がりの駅で幼なじみが再会する。 ");
  await page.getByRole("button", { name: "✦ 台本案を生成する" }).click();
  const generationDialog = page.getByRole("dialog", { name: "台本を生成しています" });
  await expect(generationDialog).toBeVisible();
  await expect(generationDialog.locator(".draft-generation-activity")).toBeVisible();
  await expect(generationDialog.locator(".draft-generation-dots")).toHaveCSS("animation-name", "scena-ellipsis");
  await expect(generationDialog.getByText("経過時間")).toBeVisible();
  await expect(generationDialog.getByText("目標文字数")).toBeVisible();
  await expect(generationDialog.getByText("全体進捗")).toBeVisible();
  await page.getByRole("button", { name: "生成をキャンセル" }).click();
  await expect(page.locator(".notice")).toContainText("キャンセル");
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await expect(page.getByRole("heading", { name: "物語の声を、ここに集める" })).toBeVisible();
});

test("switches cast assignments simultaneously and toggles a line out of batch work", async ({ page }) => {
  await page.getByRole("button", { name: "キャストの一括切り替え" }).click();
  const dialog = page.getByRole("dialog", { name: "キャストの一括切り替え" });
  await expect(dialog).toBeVisible();
  const confirm = dialog.getByRole("button", { name: "同時に切り替える" });
  await expect(confirm).toHaveCSS("color", "rgb(255, 255, 255)");
  await expect(confirm).toHaveCSS("background-color", "rgb(119, 114, 176)");
  await page.getByRole("button", { name: "キャンセル" }).click();
  const lineToggle = page.getByRole("button", { name: "発話行 1 を無効にする" });
  await expect(lineToggle).toHaveAttribute("title", "無効化");
  await lineToggle.click();
  await expect(page.getByRole("button", { name: "発話行 1 を有効にする" })).toHaveAttribute("title", "有効化");
  await expect(page.getByRole("button", { name: "発話行 1 を有効にする" })).toHaveAttribute("aria-pressed", "false");
});

test("regenerates a saved cast reference through VoiceDesign", async ({ page }) => {
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await page.getByRole("button", { name: "設定を編集" }).first().click();
  await page.getByRole("button", { name: "VoiceDesignで再生成" }).click();
  await expect(page.getByRole("dialog", { name: "声の候補をつくる" })).toBeVisible();
  await page.getByRole("button", { name: "基準ボイス候補をつくる" }).click();
  await expect(page.getByRole("status", { name: "通知" })).toContainText("声候補を追加しました");
  await page.getByRole("button", { name: "通知を閉じる" }).click();
  await page.getByRole("button", { name: "基準候補 Aを再生" }).click();
  await page.getByRole("button", { name: "参照ボイスを置き換える" }).click();
  await expect(page.locator(".notice")).toContainText("参照ボイスを更新");
});
