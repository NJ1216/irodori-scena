import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { cancelDestructiveConfirmation, confirmDestructiveAction } from "./destructiveConfirmation";
import { DestructiveConfirmationNotice } from "./DestructiveConfirmationNotice";

afterEach(() => {
  cancelDestructiveConfirmation();
  vi.useRealTimers();
});

it("shows a central question on the first action and clears it on confirmation", () => {
  vi.useFakeTimers();
  const onPending = vi.fn();
  render(<DestructiveConfirmationNotice />);
  act(() => {
    expect(confirmDestructiveAction("notice-cast", onPending, "彩を削除します。", "削除", "彩を削除しますか？", "参照WAVも削除されます。")).toBe(false);
  });
  expect(screen.getByRole("status")).toHaveTextContent("彩を削除しますか？");
  expect(screen.getByRole("status")).toHaveTextContent("参照WAVも削除されます。");
  expect(screen.getByRole("status")).toHaveTextContent("4秒以内にもう一度削除を押すと実行します");
  act(() => {
    expect(confirmDestructiveAction("notice-cast", onPending, "彩を削除します。", "削除")).toBe(true);
  });
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("removes the question when the confirmation window expires", () => {
  vi.useFakeTimers();
  render(<DestructiveConfirmationNotice />);
  act(() => {
    confirmDestructiveAction("notice-expiry", vi.fn(), "発話行を削除します。", "削除", "発話行を削除しますか？");
  });
  expect(screen.getByRole("status")).toBeVisible();
  act(() => vi.advanceTimersByTime(4_001));
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("cancels with Escape and does not treat the next delete as a second press", () => {
  vi.useFakeTimers();
  const onPending = vi.fn();
  render(<DestructiveConfirmationNotice />);
  act(() => {
    confirmDestructiveAction("escape-delete", onPending, "削除します。");
  });
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(onPending).toHaveBeenLastCalledWith("");
  act(() => {
    expect(confirmDestructiveAction("escape-delete", onPending, "削除します。")).toBe(false);
  });
});

it.each(["別の発話行", "別ページ", "別キャスト"])("cancels when selecting %s", (label) => {
  vi.useFakeTimers();
  const onPending = vi.fn();
  render(
    <>
      <DestructiveConfirmationNotice />
      <button type="button">{label}</button>
    </>,
  );
  act(() => {
    confirmDestructiveAction(`switch-${label}`, onPending, "削除します。");
  });
  fireEvent.pointerDown(screen.getByRole("button", { name: label }));
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(onPending).toHaveBeenLastCalledWith("");
  act(() => {
    expect(confirmDestructiveAction(`switch-${label}`, onPending, "削除します。")).toBe(false);
  });
});

it("keeps the pending action when the same delete button is pressed again", () => {
  vi.useFakeTimers();
  const onPending = vi.fn();
  render(
    <>
      <DestructiveConfirmationNotice />
      <button type="button" data-destructive-confirmation-key="same-delete">
        削除
      </button>
    </>,
  );
  act(() => {
    confirmDestructiveAction("same-delete", onPending, "削除します。");
  });
  fireEvent.pointerDown(screen.getByRole("button", { name: "削除" }));
  act(() => {
    expect(confirmDestructiveAction("same-delete", onPending, "削除します。")).toBe(true);
  });
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("cancels when keyboard navigation moves to another line", () => {
  vi.useFakeTimers();
  render(<DestructiveConfirmationNotice />);
  act(() => {
    confirmDestructiveAction("arrow-delete", vi.fn(), "削除します。");
  });
  fireEvent.keyDown(window, { key: "ArrowDown" });
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("replaces an old pending action when another confirmation starts", () => {
  vi.useFakeTimers();
  const firstNotice = vi.fn();
  render(<DestructiveConfirmationNotice />);
  act(() => {
    confirmDestructiveAction("old-delete", firstNotice, "古い行を削除します。");
    confirmDestructiveAction("new-delete", vi.fn(), "新しい行を削除します。");
  });
  expect(firstNotice).toHaveBeenLastCalledWith("");
  expect(screen.getByRole("status")).toHaveTextContent("新しい行を削除します。");
  act(() => {
    expect(confirmDestructiveAction("old-delete", vi.fn(), "古い行を削除します。")).toBe(false);
  });
});
