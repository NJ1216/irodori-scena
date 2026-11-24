import { afterEach, describe, expect, it } from "vitest";
import { editorCaretOffset, editorCaretRangeAtPoint, editorText } from "./editorSelection";

afterEach(() => {
  document.body.replaceChildren();
  window.getSelection()?.removeAllRanges();
});

describe("editor selection", () => {
  it("counts Unicode code points and excludes ruby readings from the caret offset", () => {
    const editor = document.createElement("div");
    editor.innerHTML = "前<ruby><span>😊後</span><rt>えがおあと</rt></ruby>半";
    document.body.append(editor);
    const rubyBase = editor.querySelector("span")?.firstChild;
    expect(rubyBase).not.toBeNull();
    const range = document.createRange();
    range.setStart(rubyBase!, 3);
    range.collapse(true);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);

    expect(editorText(editor)).toBe("前😊後半");
    expect(editorCaretOffset(editor)).toBe(3);
  });

  it("resolves a browser point caret inside the editor", () => {
    const editor = document.createElement("div");
    editor.textContent = "前後";
    document.body.append(editor);
    const text = editor.firstChild!;
    Object.defineProperty(document, "caretPositionFromPoint", { configurable: true, value: () => ({ offsetNode: text, offset: 1 }) });

    const range = editorCaretRangeAtPoint(editor, 10, 10);

    expect(range?.startContainer).toBe(text);
    expect(range?.startOffset).toBe(1);
  });

  it("moves a caret returned inside a ruby reading outside the ruby token", () => {
    const editor = document.createElement("div");
    editor.innerHTML = "前<ruby><span class='ruby-base'>後</span><rt>あと</rt></ruby>半";
    document.body.append(editor);
    const reading = editor.querySelector("rt")!.firstChild!;
    const ruby = editor.querySelector("ruby")!;
    ruby.getBoundingClientRect = () => new DOMRect(20, 0, 20, 20);
    Object.defineProperty(document, "caretPositionFromPoint", { configurable: true, value: () => ({ offsetNode: reading, offset: 1 }) });

    const range = editorCaretRangeAtPoint(editor, 45, 10);

    expect(range?.startContainer).toBe(editor);
    expect(range?.startOffset).toBe(2);
  });
});
