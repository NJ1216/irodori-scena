import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EmojiTextArea } from "./EmojiTextArea";

afterEach(() => vi.unstubAllGlobals());

function SimultaneousEditors() {
  const [values, setValues] = useState(["先頭", ""]);
  return (
    <>
      {values.map((value, index) => (
        <EmojiTextArea key={index} value={value} onChange={(text) => setValues((current) => current.map((item, itemIndex) => (itemIndex === index ? text : item)))} onCommit={vi.fn()} onTextFocus={vi.fn()} />
      ))}
    </>
  );
}

describe("EmojiTextArea simultaneous editing", () => {
  it("does not duplicate the browser-mutated content during a sibling rerender", () => {
    render(<SimultaneousEditors />);
    const editors = screen.getAllByRole("textbox");
    editors[1].textContent = "あ";
    fireEvent.input(editors[1]);
    expect(screen.getAllByRole("textbox")[1]).toHaveTextContent("あ");
    expect(screen.getAllByRole("textbox")[1]).not.toHaveTextContent("ああ");
  });

  it("opens the ruby action with Ctrl+R on Windows", () => {
    vi.stubGlobal("navigator", { platform: "Win32" });
    const notice = vi.fn();
    render(<EmojiTextArea value="本文" onChange={vi.fn()} onCommit={vi.fn()} onTextFocus={vi.fn()} onNotice={notice} />);

    fireEvent.keyDown(screen.getByRole("textbox"), { code: "KeyR", key: "r", ctrlKey: true });

    expect(notice).toHaveBeenCalledOnce();
  });

  it("undoes and redoes dialogue text inside its own editor", () => {
    render(<SimultaneousEditors />);
    let editor = screen.getAllByRole("textbox")[0];
    editor.textContent = "先頭に追記";
    fireEvent.input(editor);
    editor = screen.getAllByRole("textbox")[0];

    fireEvent.keyDown(editor, { code: "KeyZ", key: "z", metaKey: true });
    expect(screen.getAllByRole("textbox")[0]).toHaveTextContent("先頭");

    editor = screen.getAllByRole("textbox")[0];
    fireEvent.keyDown(editor, { code: "KeyZ", key: "z", metaKey: true, shiftKey: true });
    expect(screen.getAllByRole("textbox")[0]).toHaveTextContent("先頭に追記");
  });

  it("keeps each dialogue editor history independent", () => {
    render(<SimultaneousEditors />);
    const [first] = screen.getAllByRole("textbox");
    let [, second] = screen.getAllByRole("textbox");
    first.textContent = "一つ目";
    fireEvent.input(first);
    [, second] = screen.getAllByRole("textbox");
    second.textContent = "二つ目";
    fireEvent.input(second);

    [, second] = screen.getAllByRole("textbox");
    fireEvent.keyDown(second, { code: "KeyZ", key: "z", metaKey: true });

    const editors = screen.getAllByRole("textbox");
    expect(editors[0]).toHaveTextContent("一つ目");
    expect(editors[1]).toBeEmptyDOMElement();
  });

  it("records one local undo step when an IME composition is committed", () => {
    render(<SimultaneousEditors />);
    let editor = screen.getAllByRole("textbox")[1];
    fireEvent.compositionStart(editor);
    editor.textContent = "へん";
    fireEvent.input(editor);
    editor.textContent = "変換";
    fireEvent.input(editor);
    fireEvent.compositionEnd(editor);
    editor = screen.getAllByRole("textbox")[1];

    expect(editor).toHaveTextContent("変換");
    fireEvent.keyDown(editor, { code: "KeyZ", key: "z", metaKey: true });
    expect(screen.getAllByRole("textbox")[1]).toBeEmptyDOMElement();
  });

  it("does not publish intermediate IME composition text", () => {
    const onChange = vi.fn();
    render(<EmojiTextArea value="" onChange={onChange} onCommit={vi.fn()} onTextFocus={vi.fn()} />);
    const editor = screen.getByRole("textbox");
    fireEvent.compositionStart(editor);
    editor.textContent = "へん";
    fireEvent.input(editor);
    expect(onChange).not.toHaveBeenCalled();
    editor.textContent = "変換";
    fireEvent.compositionEnd(editor);
    expect(onChange).toHaveBeenCalledOnce();
    expect(onChange).toHaveBeenLastCalledWith("変換", []);
  });

  it("creates ruby for the current keyboard selection and commits it", () => {
    Object.defineProperty(Range.prototype, "getBoundingClientRect", { configurable: true, value: () => new DOMRect(0, 0, 20, 20) });
    const onChange = vi.fn();
    const onCommit = vi.fn();
    render(<EmojiTextArea value="今日です" onChange={onChange} onCommit={onCommit} onTextFocus={vi.fn()} />);
    const editor = screen.getByRole("textbox");
    const range = document.createRange();
    range.setStart(editor.firstChild!, 0);
    range.setEnd(editor.firstChild!, 2);
    window.getSelection()!.removeAllRanges();
    window.getSelection()!.addRange(range);

    fireEvent.keyDown(editor, { code: "KeyR", key: "r", metaKey: true });
    const reading = screen.getByRole("textbox", { name: "読み" });
    fireEvent.change(reading, { target: { value: "きょう" } });
    fireEvent.keyDown(reading, { key: "Enter" });

    expect(onChange).toHaveBeenCalledWith("今日です", [expect.objectContaining({ start: 0, end: 2, text: "今日", reading: "きょう" })]);
    expect(onCommit).toHaveBeenCalledOnce();
  });
});

describe("EmojiTextArea Enter keys", () => {
  it("commits with Enter and reserves Shift+Enter for a line break", () => {
    const onCommit = vi.fn();
    render(<EmojiTextArea value="台詞" onChange={vi.fn()} onCommit={onCommit} onTextFocus={vi.fn()} />);
    const editor = screen.getByRole("textbox");
    editor.focus();
    expect(fireEvent.keyDown(editor, { key: "Enter", shiftKey: true })).toBe(true);
    expect(onCommit).not.toHaveBeenCalled();
    expect(fireEvent.keyDown(editor, { key: "Enter" })).toBe(false);
    expect(onCommit).toHaveBeenCalledOnce();
    expect(editor).not.toHaveFocus();
  });

  it("does not commit while Japanese text is being composed", () => {
    const onCommit = vi.fn();
    render(<EmojiTextArea value="台詞" onChange={vi.fn()} onCommit={onCommit} onTextFocus={vi.fn()} />);
    const editor = screen.getByRole("textbox");
    editor.focus();
    fireEvent.compositionStart(editor);
    expect(fireEvent.keyDown(editor, { key: "Enter" })).toBe(true);
    expect(onCommit).not.toHaveBeenCalled();
    expect(editor).toHaveFocus();
  });
});

it("copies only visible base text and excludes ruby readings", () => {
  render(<EmojiTextArea value="今日" pronunciations={[{ id: "ruby-1", start: 0, end: 2, text: "今日", reading: "きょう" }]} onChange={vi.fn()} onCommit={vi.fn()} onTextFocus={vi.fn()} />);
  const editor = screen.getByRole("textbox");
  const range = document.createRange();
  range.selectNodeContents(editor);
  window.getSelection()!.removeAllRanges();
  window.getSelection()!.addRange(range);
  const setData = vi.fn();
  fireEvent.copy(editor, { clipboardData: { setData } });
  expect(setData).toHaveBeenCalledWith("text/plain", "今日");
});
