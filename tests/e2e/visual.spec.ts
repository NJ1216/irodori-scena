import { expect, test } from "@playwright/test";
import { installMockApi } from "./mock-api";

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installMockApi(page);
});

test("script desktop", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "SCRIPT TITLE 雨上がりの約束" })).toBeVisible();
  await expect(page).toHaveScreenshot("script-desktop.png", {
    animations: "disabled",
  });
});

test("AI direction dialog keeps all controls and actions visible", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 1900 });
  await page.goto("/");
  await page.locator(".project-menu").hover();
  await page.getByRole("button", { name: "AI演出" }).click();
  const dialog = page.locator(".ai-direction-dialog");
  // A z-index number cannot prove stacking across distinct stacking contexts.
  const heading = dialog.getByRole("heading").first();
  await expect
    .poll(() =>
      heading.evaluate((element) => {
        const bounds = element.getBoundingClientRect();
        const hit = document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
        return hit !== null && element.contains(hit);
      }),
    )
    .toBe(true);
  await expect(dialog).toHaveScreenshot("ai-direction-dialog.png", {
    animations: "disabled",
  });
  await expect(dialog.getByRole("button", { name: "キャンセル" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "AI演出を反映" })).toBeVisible();
  const append = dialog.getByRole("radio", { name: "追加", exact: true });
  await append.click();
  await expect(append).toBeChecked();
  await dialog.getByRole("button", { name: "キャンセル", exact: true }).click();
  await expect(dialog).toHaveCount(0);
});

test("cast editor keeps reference-voice controls compact", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await page.getByRole("button", { name: "設定を編集" }).first().click();
  const dialog = page.getByRole("heading", { name: "キャストの設定を編集" }).locator("..").locator("..").locator("..");
  await expect(page.locator(".modal-backdrop")).toHaveCSS("z-index", "100");
  const voiceLabel = dialog.getByText("ボイス", { exact: true });
  const nameLabel = dialog.locator("label").filter({ hasText: "表示名" });
  await expect(voiceLabel).toHaveCSS("font-size", "12px");
  await expect(nameLabel).toHaveCSS("font-size", "12px");
  await expect(dialog.getByLabel("現在の参照ボイス", { exact: true })).toBeVisible();
  await expect(dialog.getByLabel("現在の参照ボイスの再生位置")).toBeVisible();
  await expect(dialog.getByLabel("現在の参照ボイス", { exact: true })).not.toHaveAttribute("controls", "");
  await expect(dialog.getByRole("button", { name: "WAVファイルを指定" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "VoiceDesignで再生成" })).toBeVisible();
  await expect(dialog.locator(".reference-wav-file-input")).toBeHidden();
  await expect(dialog).not.toContainText("RIFF/WAVE");
  await expect(dialog).toHaveScreenshot("cast-edit-voice.png", { animations: "disabled" });
});

test("secondary hair color controls appear only when enabled", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await page.getByRole("button", { name: "設定を編集" }).first().click();
  await page.getByRole("button", { name: "画像生成用プロンプト文を作る" }).click();

  const lengthMenu = page.getByRole("button", { name: "長さの候補を表示" });
  const hairstyleMenu = page.getByRole("button", { name: "ヘアスタイルの候補を表示" });
  const lengthInput = page.locator(".image-prompt-combobox").filter({ hasText: "長さ" }).first().locator("input");
  const [lengthInputBox, lengthMenuBox] = await Promise.all([lengthInput.boundingBox(), lengthMenu.boundingBox()]);
  expect(lengthInputBox).not.toBeNull();
  expect(lengthMenuBox).not.toBeNull();
  expect(Math.abs(lengthInputBox!.y + lengthInputBox!.height / 2 - (lengthMenuBox!.y + lengthMenuBox!.height / 2))).toBeLessThanOrEqual(1);
  await lengthMenu.click();
  await expect(lengthMenu).toHaveAttribute("aria-expanded", "true");
  await hairstyleMenu.click();
  await expect(lengthMenu).toHaveAttribute("aria-expanded", "false");
  await expect(hairstyleMenu).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".image-prompt-combobox-menu")).toHaveCount(1);

  const toggle = page.getByRole("checkbox", { name: "髪色2を使う" });
  const secondaryColor = page.locator(".image-prompt-color-combobox").filter({ hasText: "髪色2" });
  await expect(toggle).not.toBeChecked();
  await expect(secondaryColor).toHaveCount(0);

  await toggle.check();
  await expect(secondaryColor).toBeVisible();
  await secondaryColor.locator('input:not([type="color"])').fill("#D96B9B");
  await page.getByRole("button", { name: "配色方式の候補を表示" }).click();
  await page.getByRole("option", { name: "インナーカラー" }).click();
  await expect(secondaryColor.locator('input:not([type="color"])')).toHaveValue("#D96B9B");
  await expect(page.getByRole("textbox", { name: /配色方式/ })).toHaveValue("インナーカラー");

  await toggle.uncheck();
  await expect(secondaryColor).toHaveCount(0);
});

test("image prompt detail controls use single gestures and conditional backgrounds", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await page.getByRole("button", { name: "設定を編集" }).first().click();
  await page.getByRole("button", { name: "画像生成用プロンプト文を作る" }).click();

  await expect(page.getByRole("textbox", { name: "身長" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "手・腕ジェスチャー" })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /ピース/ })).toHaveCount(0);
  await expect(page.getByRole("group", { name: "識別特徴" })).toHaveCount(0);

  await page.getByRole("textbox", { name: "背景の種類" }).fill("単色");
  await expect(page.getByRole("textbox", { name: "背景色" })).toBeVisible();
  await page.getByRole("textbox", { name: "背景の種類" }).fill("グラデーション");
  await expect(page.getByRole("textbox", { name: "グラデーション色1" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "グラデーション色2" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "グラデーション方向" })).toBeVisible();
});

test("header submenu appears above the notice", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await page.locator(".project-menu").hover();
  const submenu = page.locator(".project-submenu");
  await expect(submenu).toBeVisible();
  expect(
    await submenu.evaluate((menu) => {
      const rect = menu.getBoundingClientRect();
      const topmost = document.elementFromPoint(rect.left + 8, rect.top + 8);
      return Boolean(topmost && menu.contains(topmost));
    }),
  ).toBe(true);
});

test("auto-generation status keeps a fixed circular icon", async ({ page }) => {
  await page.goto("/");
  const button = page.locator(".auto-generate-button");
  const icon = button.locator(".auto-generate-status-icon");
  await expect(icon).toHaveCSS("width", "16px");
  await expect(icon).toHaveCSS("height", "16px");
  await expect(icon).toHaveCSS("border-radius", "50%");
  await expect(button).toHaveAttribute("aria-pressed", "true");
  await button.click();
  await expect(button).toHaveAttribute("aria-pressed", "false");
  await button.click();
  await expect(button).toHaveAttribute("aria-pressed", "true");
  await expect(button).toHaveCSS("background-color", "rgb(223, 120, 149)");
  await expect(button).toHaveCSS("color", "rgb(255, 255, 255)");
  await expect(icon).toHaveCSS("background-color", "rgb(255, 255, 255)");
});

test("pronunciation LLM toggle uses the circular status treatment", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "辞書", exact: true }).click();
  const toggle = page.getByRole("checkbox", { name: "LLMの使用" });
  await expect(toggle).toHaveCSS("width", "16px");
  await expect(toggle).toHaveCSS("height", "16px");
  await expect(toggle).toHaveCSS("border-radius", "50%");
  await toggle.check();
  await expect(toggle).toHaveCSS("background-color", "rgb(112, 168, 163)");
});

test("cast dictionary actions respect the LLM toggle and choose a cast", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "辞書", exact: true }).click();
  const toggle = page.getByRole("checkbox", { name: "LLMの使用" });
  const castDictionary = page.locator(".cast-dictionary-section");
  const manualDictionary = page.locator(".manual-dictionary-section");
  for (const heading of [castDictionary.getByRole("heading"), manualDictionary.getByRole("heading")]) {
    await expect(heading).toHaveCSS("font-size", "15px");
    await expect(heading).toHaveCSS("line-height", "18px");
    await expect(heading).toHaveCSS("font-weight", "700");
    await expect(heading).toHaveCSS("color", "rgb(72, 69, 110)");
    const icon = await heading.evaluate((element) => {
      const style = getComputedStyle(element, "::before");
      return { width: style.width, height: style.height, mask: style.maskImage };
    });
    expect(icon).toMatchObject({ width: "16px", height: "16px" });
    expect(icon.mask).not.toBe("none");
    const actions = heading.locator("xpath=..").locator(".dictionary-section-actions");
    await expect
      .poll(async () => {
        const [titleBox, actionBox] = await Promise.all([heading.boundingBox(), actions.boundingBox()]);
        return Math.abs(titleBox!.y + titleBox!.height / 2 - (actionBox!.y + actionBox!.height / 2));
      })
      .toBeLessThanOrEqual(3);
  }
  const titleIcons = await Promise.all([castDictionary, manualDictionary].map((section) => section.getByRole("heading").evaluate((element) => getComputedStyle(element, "::before").maskImage)));
  expect(titleIcons[0]).not.toBe(titleIcons[1]);
  await toggle.uncheck();
  await expect(page.getByRole("button", { name: "キャスト情報を更新" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "台本から追加" })).toHaveCount(0);
  await expect(castDictionary.getByRole("button", { name: "読みを推測" })).toHaveCount(0);
  await toggle.check();
  await expect(castDictionary.getByRole("button", { name: "読みを推測" })).toBeVisible();
  await expect(manualDictionary.getByRole("button", { name: "読みを推測" })).toBeVisible();
  await castDictionary.getByRole("button", { name: "＋ 単語を追加" }).click();
  await expect(castDictionary.getByLabel("対象キャスト")).toHaveValue("cast-sara");
  await expect(castDictionary.locator(".cast-avatar-picker .dictionary-avatar")).toBeVisible();
});

test("script desktop scrolls from the background", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  const speakerRailTop = await page.locator(".speaker-rail").evaluate((rail) => Math.round(rail.getBoundingClientRect().top));
  const speakerRail = page.locator(".speaker-rail");
  const headerBottom = await page.locator(".app-header").evaluate((header) => Math.round(header.getBoundingClientRect().bottom));
  await expect
    .poll(() =>
      speakerRail
        .locator(":scope > *")
        .first()
        .evaluate((panel) => Math.round(panel.getBoundingClientRect().top)),
    )
    .toBeGreaterThan(headerBottom);
  await expect.poll(() => speakerRail.evaluate((rail) => rail.scrollHeight > rail.clientHeight)).toBe(true);
  await expect.poll(() => speakerRail.evaluate((rail) => Math.round(rail.getBoundingClientRect().bottom))).toBe(800);
  const railScrollbar = page.getByRole("scrollbar", { name: "台本のキャストレール" });
  await speakerRail.evaluate((rail) => rail.dispatchEvent(new WheelEvent("wheel", { deltaY: 200 })));
  await expect(railScrollbar).toBeVisible();
  const railBar = await railScrollbar.locator("..").boundingBox();
  expect(Math.round(railBar?.y ?? 0)).toBe(headerBottom);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await page.locator(".script-canvas").evaluate((canvas) => {
    const spacer = document.createElement("div");
    spacer.style.height = "1600px";
    canvas.append(spacer);
  });
  await page.locator(".script-canvas").hover();
  await page.mouse.wheel(0, 200);
  const canvasScrollbar = page.getByRole("scrollbar", { name: "台本キャンバス" });
  await expect(canvasScrollbar).toBeVisible();
  const [canvasBar, footer] = await Promise.all([canvasScrollbar.locator("..").boundingBox(), page.locator(".main-window-footer").boundingBox()]);
  expect(Math.round((canvasBar?.y ?? 0) + (canvasBar?.height ?? 0))).toBe(Math.round(footer?.y ?? 0));
  expect(Math.round((canvasBar?.x ?? 0) + (canvasBar?.width ?? 0))).toBe(1280);
  await page.locator(".script-canvas").hover();
  await page.mouse.wheel(0, 600);
  await expect.poll(() => page.locator(".script-canvas").evaluate((canvas) => canvas.scrollTop)).toBeGreaterThan(0);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await expect(page.locator(".app-header")).toHaveCSS("position", "fixed");
  await expect(page.locator(".speaker-rail")).toHaveCSS("position", "static");
  await expect(page.locator(".script-title-editor")).toHaveCSS("position", "relative");
  await expect.poll(() => page.locator(".notice").evaluate((notice) => Math.round(notice.getBoundingClientRect().top))).toBe(76);
  await expect.poll(() => page.locator(".speaker-rail").evaluate((rail) => Math.round(rail.getBoundingClientRect().top))).toBe(speakerRailTop);
  await expect.poll(() => speakerRail.evaluate((rail) => rail.scrollTop)).toBe(0);
  await expect.poll(() => page.locator(".script-title-editor").evaluate((title) => Math.round(title.getBoundingClientRect().top))).toBeLessThan(0);
  await page.evaluate(() => window.scrollTo({ left: 500 }));
  await expect.poll(() => page.evaluate(() => window.scrollX)).toBe(0);
});

test("script canvas uses the available desktop width", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto("/");

  const bounds = await page.locator(".workspace").evaluate((workspace) => {
    const canvas = workspace.querySelector(".script-canvas");
    if (!canvas) throw new Error("Script canvas was not rendered");
    return {
      workspace: workspace.getBoundingClientRect().width,
      canvas: canvas.getBoundingClientRect().width,
    };
  });

  expect(bounds.workspace).toBe(1640);
  expect(bounds.canvas).toBeGreaterThan(1290);
});

test("script narrow layout confines its workspace scrollbar between window chrome", async ({ page }) => {
  await page.setViewportSize({ width: 1080, height: 800 });
  await page.goto("/");

  const workspace = page.locator(".workspace");
  await page.locator(".script-canvas").evaluate((canvas) => {
    const spacer = document.createElement("div");
    spacer.style.height = "1600px";
    canvas.append(spacer);
  });
  await workspace.hover();
  await page.mouse.wheel(0, 600);
  await expect.poll(() => workspace.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  await expect(page.getByRole("scrollbar", { name: "台本", exact: true })).toBeVisible();
  const workspaceScrollbar = await page.getByRole("scrollbar", { name: "台本", exact: true }).locator("..").boundingBox();
  expect(Math.round((workspaceScrollbar?.x ?? 0) + (workspaceScrollbar?.width ?? 0))).toBe(1080);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
});

test("script and cast share the desktop page gutters", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/");
  const scriptBounds = await page.locator(".workspace").evaluate((workspace) => {
    const style = getComputedStyle(workspace);
    const bounds = workspace.getBoundingClientRect();
    return {
      left: bounds.left + Number.parseFloat(style.paddingLeft),
      right: bounds.right - Number.parseFloat(style.paddingRight),
    };
  });

  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  const castBounds = await page.locator(".saved-characters").evaluate((container) => {
    const bounds = container.getBoundingClientRect();
    return { left: bounds.left, right: bounds.right };
  });

  expect(castBounds).toEqual(scriptBounds);
});

test("cast container stops at the script content width on wide windows", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto("/");
  const scriptBounds = await page.locator(".workspace").evaluate((workspace) => {
    const style = getComputedStyle(workspace);
    const bounds = workspace.getBoundingClientRect();
    return {
      left: bounds.left + Number.parseFloat(style.paddingLeft),
      right: bounds.right - Number.parseFloat(style.paddingRight),
      width: bounds.width - Number.parseFloat(style.paddingLeft) - Number.parseFloat(style.paddingRight),
    };
  });

  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  const castBounds = await page.locator(".saved-characters").evaluate((container) => {
    const bounds = container.getBoundingClientRect();
    return { left: bounds.left, right: bounds.right, width: bounds.width };
  });
  const castPageContent = await page.locator(".characters-page").evaluate((container) => {
    const style = getComputedStyle(container);
    const bounds = container.getBoundingClientRect();
    return {
      left: bounds.left + Number.parseFloat(style.paddingLeft),
      right: bounds.right - Number.parseFloat(style.paddingRight),
      width: bounds.width - Number.parseFloat(style.paddingLeft) - Number.parseFloat(style.paddingRight),
    };
  });
  const castSectionLeftEdges = await Promise.all([
    page.locator(".character-heading").evaluate((element) => element.getBoundingClientRect().left),
    page.locator(".cast-action-buttons").evaluate((element) => element.getBoundingClientRect().left),
    page.locator(".saved-characters").evaluate((element) => element.getBoundingClientRect().left),
  ]);

  expect(castBounds).toEqual(scriptBounds);
  expect(castPageContent).toEqual(scriptBounds);
  expect(new Set(castSectionLeftEdges)).toEqual(new Set([scriptBounds.left]));
  expect(castBounds.width).toBe(1600);
});

test("all page title rows share the script content edge", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto("/");
  const scriptLeft = await page.locator(".workspace").evaluate((workspace) => {
    const style = getComputedStyle(workspace);
    return workspace.getBoundingClientRect().left + Number.parseFloat(style.paddingLeft);
  });

  for (const tab of ["キャスト", "辞書", "AI台本", "設定"]) {
    await page.getByRole("button", { name: tab, exact: true }).click();
    await expect(page.locator(".page:not([hidden])")).toBeVisible();
    const pageWidth = await page.locator(".page:not([hidden])").evaluate((pageElement) => pageElement.getBoundingClientRect().width);
    const titleLeft = await page.locator(".page:not([hidden]) .page-heading").evaluate((heading) => heading.getBoundingClientRect().left);
    expect(pageWidth, `${tab}ページの外枠幅`).toBe(1640);
    expect(titleLeft, `${tab}ページのタイトル位置`).toBe(scriptLeft);
  }

  await page.getByRole("button", { name: "辞書", exact: true }).click();
  await expect(page.locator(".pronunciation-dictionary-columns")).toHaveCSS("max-width", "1320px");
  const [toggleRight, manualTableRight] = await Promise.all([page.getByText("LLMの使用", { exact: true }).evaluate((element) => element.getBoundingClientRect().right), page.locator(".manual-dictionary-section .dictionary-table-wrap").evaluate((element) => element.getBoundingClientRect().right)]);
  expect(toggleRight).toBeLessThanOrEqual(manualTableRight);
});

test("dictionary, AI draft, and settings use their own gutter scrollbars", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");

  for (const [tab, label] of [
    ["辞書", "辞書ページ"],
    ["AI台本", "AI台本ページ"],
    ["設定", "設定ページ"],
  ] as const) {
    await page.getByRole("button", { name: tab, exact: true }).click();
    const scroller = page.locator(".page:not([hidden])");
    await expect(scroller).toBeVisible();
    await scroller.evaluate((element) => {
      const spacer = document.createElement("div");
      spacer.dataset.scrollbarFixture = "true";
      spacer.style.height = "1600px";
      element.append(spacer);
    });
    await scroller.hover();
    await page.mouse.wheel(0, 400);
    await expect.poll(() => scroller.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
    const scrollbar = page.getByRole("scrollbar", { name: label });
    await expect(scrollbar).toBeVisible();
    const [bar, pageBounds] = await Promise.all([scrollbar.locator("..").boundingBox(), scroller.boundingBox()]);
    expect(bar!.x).toBeGreaterThan(pageBounds!.x + pageBounds!.width - 20);
    expect(bar!.x + bar!.width).toBeLessThanOrEqual(pageBounds!.x + pageBounds!.width);
    await expect(page.getByRole("scrollbar", { name: "台本", exact: true })).toHaveCount(0);
    await expect(page.getByRole("scrollbar", { name: "台本キャンバス", exact: true })).toHaveCount(0);
    await expect(page.getByRole("scrollbar", { name: "台本のキャストレール", exact: true })).toHaveCount(0);
  }
});

test("cast notebook at 1140px", async ({ page }) => {
  await page.setViewportSize({ width: 1140, height: 800 });
  await page.goto("/");
  await page.getByRole("button", { name: "キャスト", exact: true }).click();
  await expect(page.locator(".cast-notebook")).toHaveScreenshot("cast-notebook-1140.png", {
    animations: "disabled",
  });
});

test("cast notebook actions occupy the last complete ruled line", async ({ page }) => {
  await page.setViewportSize({ width: 1140, height: 800 });
  await page.goto("/");
  await page.getByRole("button", { name: "キャスト", exact: true }).click();

  const actionLayout = () =>
    page.locator(".cast-notebook-page.is-left").evaluate((pageElement) => {
      const actions = pageElement.querySelector(".cast-notebook-actions");
      const content = pageElement.querySelector(".cast-notebook-profile-content");
      const spacer = pageElement.querySelector(".cast-notebook-action-spacer");
      if (!actions || !content || !spacer) throw new Error("Notebook layout is incomplete");
      const pageRect = pageElement.getBoundingClientRect();
      const actionsRect = actions.getBoundingClientRect();
      const contentRect = content.getBoundingClientRect();
      const style = getComputedStyle(pageElement);
      const ruleHeight = Number.parseFloat(style.getPropertyValue("--cast-notebook-rule-height"));
      const paddingBottom = Number.parseFloat(style.paddingBottom);
      const spacerHeight = spacer.getBoundingClientRect().height;
      const remainingHeight = pageRect.bottom - paddingBottom - actionsRect.bottom;
      return {
        ruleHeight,
        spacerHeight,
        contentEnd: contentRect.bottom - pageRect.top,
        actionTop: actionsRect.top - pageRect.top,
        remainingHeight,
      };
    });

  for (const width of [1140, 900]) {
    if (width !== 1140) {
      await page.locator(".cast-notebook").evaluate((element, nextWidth) => {
        (element as HTMLElement).style.width = `${nextWidth}px`;
      }, width);
    }
    await expect
      .poll(async () => {
        const layout = await actionLayout();
        return layout.spacerHeight % layout.ruleHeight === 0 && layout.remainingHeight >= 0 && layout.remainingHeight < layout.ruleHeight;
      })
      .toBe(true);
    const layout = await actionLayout();
    expect(layout.spacerHeight % layout.ruleHeight).toBeCloseTo(0, 5);
    expect(layout.actionTop).toBeGreaterThanOrEqual(layout.contentEnd);
    expect(layout.remainingHeight).toBeGreaterThanOrEqual(0);
    expect(layout.remainingHeight).toBeLessThan(layout.ruleHeight);
  }
});
