// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DialogNoticeOverlay } from "./DialogNoticeOverlay";

function openDialog() {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  document.body.append(backdrop);
  return backdrop;
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  document.querySelectorAll(".modal-backdrop, [aria-modal], input").forEach((element) => element.remove());
});

const overlay = () => screen.queryByRole("status", { name: "通知" });
const scrim = () => document.querySelector(".notice-overlay-scrim");

function raise(text: string) {
  const view = render(<DialogNoticeOverlay text="" serial={0} />);
  view.rerender(<DialogNoticeOverlay text={text} serial={1} />);
  return view;
}

it("shows a notice raised while a dialog is open in the shared centered notice over a dimming scrim", () => {
  const { rerender } = render(<DialogNoticeOverlay text="準備中" serial={0} />);
  expect(overlay()).toBeNull();
  openDialog();
  rerender(<DialogNoticeOverlay text="候補を作れませんでした: 試聴台詞を短くしてください。" serial={1} />);
  expect(overlay()).toHaveTextContent("試聴台詞を短くしてください。");
  expect(overlay()).toHaveClass("centered-notice", "is-neutral");
  expect(scrim()).not.toBeNull();
});

it("leaves notices raised without a dialog to the header area", () => {
  raise("保存しました。");
  expect(overlay()).toBeNull();
  expect(scrim()).toBeNull();
});

it("also detects an aria-modal dialog without a shared backdrop", () => {
  const dialog = document.createElement("section");
  dialog.setAttribute("aria-modal", "true");
  document.body.append(dialog);
  raise("読み込みました。");
  expect(overlay()).toHaveTextContent("読み込みました。");
});

it("stays until it is dismissed", () => {
  openDialog();
  raise("追加しました。");
  act(() => vi.advanceTimersByTime(60_000));
  expect(overlay()).not.toBeNull();
});

it("closes with its close button", () => {
  openDialog();
  raise("追加しました。");
  fireEvent.click(screen.getByRole("button", { name: "通知を閉じる" }));
  expect(overlay()).toBeNull();
  expect(scrim()).toBeNull();
});

it("closes when the dimmed area is clicked", () => {
  openDialog();
  raise("追加しました。");
  fireEvent.mouseDown(scrim()!);
  fireEvent.click(scrim()!);
  expect(overlay()).toBeNull();
});

it("closes with Escape without letting the dialog see that Escape", () => {
  openDialog();
  const dialogEscape = vi.fn();
  window.addEventListener("keydown", dialogEscape);
  raise("追加しました。");
  fireEvent.keyDown(document.body, { key: "Escape" });
  expect(overlay()).toBeNull();
  expect(dialogEscape).not.toHaveBeenCalled();
  fireEvent.keyDown(document.body, { key: "Escape" });
  expect(dialogEscape).toHaveBeenCalledTimes(1);
  window.removeEventListener("keydown", dialogEscape);
});

it("moves focus to the close button and returns it to the previous control", () => {
  openDialog();
  const input = document.createElement("input");
  document.body.append(input);
  input.focus();
  raise("入力してください。");
  expect(screen.getByRole("button", { name: "通知を閉じる" })).toHaveFocus();
  fireEvent.keyDown(document.body, { key: "Escape" });
  expect(input).toHaveFocus();
});

it("shows a repeated identical notice again and replaces the text for a newer one", () => {
  openDialog();
  const { rerender } = render(<DialogNoticeOverlay text="" serial={0} />);
  rerender(<DialogNoticeOverlay text="失敗しました。" serial={1} />);
  fireEvent.click(screen.getByRole("button", { name: "通知を閉じる" }));
  rerender(<DialogNoticeOverlay text="失敗しました。" serial={2} />);
  expect(overlay()).toHaveTextContent("失敗しました。");
  rerender(<DialogNoticeOverlay text="成功しました。" serial={3} />);
  expect(overlay()).toHaveTextContent("成功しました。");
});

it("does not cover a dialog with progress notices raised while work is running", () => {
  openDialog();
  const { rerender } = render(<DialogNoticeOverlay text="" serial={0} busy />);
  rerender(<DialogNoticeOverlay text="台本を生成しています…" serial={1} busy />);
  expect(overlay()).toBeNull();
  rerender(<DialogNoticeOverlay text="台本の生成をキャンセルしました。" serial={2} busy={false} />);
  expect(overlay()).toHaveTextContent("キャンセルしました。");
});

it("ignores an empty notice", () => {
  openDialog();
  raise("  ");
  expect(overlay()).toBeNull();
});

it("keeps status updates (a text change without a new serial) out of the overlay, even after the overlay is closed", () => {
  openDialog();
  const { rerender } = render(<DialogNoticeOverlay text="" serial={0} />);
  rerender(<DialogNoticeOverlay text="共通タイムラインを再生しています。" serial={0} />);
  expect(overlay()).toBeNull();
  rerender(<DialogNoticeOverlay text="「ミナ」の画像を更新しました。" serial={1} />);
  expect(overlay()).toHaveTextContent("画像を更新しました。");
  fireEvent.click(screen.getByRole("button", { name: "通知を閉じる" }));
  rerender(<DialogNoticeOverlay text="音声を待っています…" serial={1} />);
  rerender(<DialogNoticeOverlay text="共通タイムラインを再生しています。" serial={1} />);
  expect(overlay()).toBeNull();
});
