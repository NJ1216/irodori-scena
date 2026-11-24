import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { StudioProject } from "../../types";
import { useScriptEditorKeyboard } from "./useScriptEditorKeyboard";
import { editorCaretOffset } from "./editorSelection";

vi.mock("./editorSelection", () => ({ editorCaretOffset: vi.fn(() => 2), editorText: () => "abc" }));

function KeyboardFixture({ onCommit = vi.fn(async (_lineId: string, _autoRender: boolean) => true), onSplit = vi.fn(async (_sceneId: string, _lineId: string, _offset: number) => true), onQueue = vi.fn((_lineId: string) => {}) }) {
  const onKeyDown = useScriptEditorKeyboard({
    project: { scenes: [{ id: "scene", lines: [{ id: "line" }] }] } as StudioProject,
    onCommitLineContent: onCommit,
    onSplitLine: onSplit,
    onQueueAutoRender: onQueue,
  });
  return (
    <section className="script-canvas" onKeyDown={onKeyDown}>
      <div className="line-main" data-line-id="line">
        <span className="line-text-editor" role="textbox" tabIndex={0}>
          abc
        </span>
      </div>
      <div className="line-main" data-line-id="next">
        <span className="line-text-editor" role="textbox" tabIndex={0}>
          next
        </span>
      </div>
    </section>
  );
}

it("commits before splitting at the caret with the primary modifier", async () => {
  const onCommit = vi.fn(async () => true);
  const onSplit = vi.fn(async () => true);
  render(<KeyboardFixture onCommit={onCommit} onSplit={onSplit} />);
  fireEvent.keyDown(screen.getAllByRole("textbox")[0], { key: "Enter", metaKey: true });
  await waitFor(() => expect(onSplit).toHaveBeenCalledWith("scene", "line", 2));
  expect(onCommit).toHaveBeenCalledWith("line", false);
  expect(onCommit.mock.invocationCallOrder[0]).toBeLessThan(onSplit.mock.invocationCallOrder[0]);
});

it("does not split when commit rejects the current draft", async () => {
  const onCommit = vi.fn(async () => false);
  const onSplit = vi.fn(async () => true);
  render(<KeyboardFixture onCommit={onCommit} onSplit={onSplit} />);
  fireEvent.keyDown(screen.getAllByRole("textbox")[0], { key: "Enter", metaKey: true });
  await waitFor(() => expect(onCommit).toHaveBeenCalled());
  expect(onSplit).not.toHaveBeenCalled();
});

it("starts automatic generation only after the next line has been created", async () => {
  vi.mocked(editorCaretOffset).mockReturnValueOnce(3);
  const order: string[] = [];
  const onCommit = vi.fn(async (_lineId: string, autoRender: boolean) => {
    expect(autoRender).toBe(false);
    order.push("commit");
    return true;
  });
  const onSplit = vi.fn(async () => {
    order.push("split");
    return true;
  });
  const onQueue = vi.fn((_lineId: string) => {
    order.push("queue");
  });
  render(<KeyboardFixture onCommit={onCommit} onSplit={onSplit} onQueue={onQueue} />);
  fireEvent.keyDown(screen.getAllByRole("textbox")[0], { key: "Enter", metaKey: true });
  await waitFor(() => expect(onQueue).toHaveBeenCalledWith("line"));
  expect(order).toEqual(["commit", "split", "queue"]);
});

it("cycles line editors with Tab and Shift+Tab", () => {
  render(<KeyboardFixture />);
  const editors = screen.getAllByRole("textbox");
  editors[0].focus();
  fireEvent.keyDown(editors[0], { key: "Tab" });
  expect(editors[1]).toHaveFocus();
  fireEvent.keyDown(editors[1], { key: "Tab", shiftKey: true });
  expect(editors[0]).toHaveFocus();
});
