import { expect, test, type Locator } from "@playwright/test";
import { installMockApi } from "./mock-api";

async function placeCaret(editor: Locator, offset: number) {
  await editor.evaluate((element, point) => {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    const node = walker.nextNode();
    if (!node) throw new Error("Dialogue editor has no text node.");
    const range = document.createRange();
    range.setStart(node, point);
    range.collapse(true);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    (element as HTMLElement).focus();
  }, offset);
}

test("Cmd/Ctrl+Enter splits at the caret and inherits only middle-split performance settings", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");

  const editors = page.locator(".line-text-editor");
  const first = editors.first();
  const firstCard = page.locator(".line-card").first();
  await firstCard.locator(".line-meta").hover();
  await firstCard.getByRole("button", { name: "行ごとのCFG設定を表示" }).click();
  await firstCard.getByLabel("発話行ごとのtextCfg（台詞への追従）").fill("4.2");
  await firstCard.getByLabel("発話行ごとのvoiceCfg（基準ボイスへの追従）").fill("6.3");
  await firstCard.getByLabel("発話行ごとのcaptionCfg（ト書きへの追従）").fill("7.4");
  await firstCard.getByLabel("発話行ごとのcaptionCfg（ト書きへの追従）").blur();
  await placeCaret(first, 2);
  await first.press("ControlOrMeta+Enter");

  await expect(editors).toHaveCount(3);
  await expect(editors.nth(0)).toHaveText("雨、");
  await expect(editors.nth(1)).toHaveText("やっと上がったね。");
  await expect(editors.nth(1)).toBeFocused();
  const splitCard = page.locator(".line-card").nth(1);
  await expect(splitCard.getByLabel("発話行ごとの話速")).toHaveValue("1");
  await expect(splitCard.getByLabel("発話行ごとの発話間隔（秒）")).toHaveValue("0.7");
  await splitCard.locator(".line-meta").hover();
  await splitCard.getByRole("button", { name: "行ごとのCFG設定を表示" }).click();
  await expect(splitCard.getByLabel("発話行ごとのtextCfg（台詞への追従）")).toHaveValue("4.2");
  await expect(splitCard.getByLabel("発話行ごとのvoiceCfg（基準ボイスへの追従）")).toHaveValue("6.3");
  await expect(splitCard.getByLabel("発話行ごとのcaptionCfg（ト書きへの追従）")).toHaveValue("7.4");

  const suffix = editors.nth(1);
  await placeCaret(suffix, "やっと上がったね。".length);
  await suffix.press("ControlOrMeta+Enter");

  await expect(editors).toHaveCount(4);
  await expect(editors.nth(2)).toHaveText("");
  await expect(editors.nth(2)).toBeFocused();
  const blankCard = page.locator(".line-card").nth(2);
  await expect(blankCard.getByLabel("発話行ごとの話速")).toHaveValue("");
  await expect(blankCard.getByLabel("発話行ごとの発話間隔（秒）")).toHaveValue("");
});
