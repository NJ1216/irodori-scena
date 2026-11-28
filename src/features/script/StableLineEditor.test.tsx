// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { LineEditorProps } from "./LineEditor";
import { sameLineEditorProps } from "./stableLineEditorProps";

const renders = vi.hoisted(() => ({ count: 0, last: null as null | Record<string, unknown> }));
vi.mock("./LineEditor", () => ({
  LineEditor: (props: Record<string, unknown>) => {
    renders.count++;
    renders.last = props;
    return null;
  },
}));
const { StableLineEditor } = await import("./StableLineEditor");

function props(overrides: Record<string, unknown>) {
  return { line: { id: "a" }, selected: false, rewriteTargetLineIds: ["a"], onFocusLine: () => undefined, ...overrides } as unknown as LineEditorProps;
}

it("skips a line card whose data is unchanged and calls the newest handler", () => {
  const line = { id: "a" };
  const first = vi.fn();
  const second = vi.fn();
  const view = render(<StableLineEditor {...props({ line, onFocusLine: first })} />);
  view.rerender(<StableLineEditor {...props({ line, onFocusLine: second, rewriteTargetLineIds: ["a"] })} />);
  expect(renders.count).toBe(1);
  (renders.last!.onFocusLine as (value: unknown) => void)("shift");
  expect(first).not.toHaveBeenCalled();
  expect(second).toHaveBeenCalledWith("shift");
  view.rerender(<StableLineEditor {...props({ line, onFocusLine: second, selected: true })} />);
  expect(renders.count).toBe(2);
  view.rerender(<StableLineEditor {...props({ line, onFocusLine: second, selected: true, onSetSelectedGaps: () => undefined })} />);
  expect(renders.count).toBe(3);
  view.rerender(<StableLineEditor {...props({ line: { id: "a" }, onFocusLine: second, selected: true, onSetSelectedGaps: () => undefined })} />);
  expect(renders.count).toBe(4);
});

it("compares arrays by their items", () => {
  const cast = { id: "c" };
  expect(sameLineEditorProps({ list: [cast] }, { list: [cast] })).toBe(true);
  expect(sameLineEditorProps({ list: [cast] }, { list: [{ id: "c" }] })).toBe(false);
  expect(sameLineEditorProps({ a: 1 }, { a: 1, b: undefined })).toBe(true);
  expect(sameLineEditorProps({ a: 1 }, { a: 1, b: 2 })).toBe(false);
});
