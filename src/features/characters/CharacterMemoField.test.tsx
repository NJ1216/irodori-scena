// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CharacterMemoField } from "./CharacterMemoField";
import { characterMemoLength, characterMemoLimitError, reportCharacterMemoLimit } from "./characterMemo";

it("counts Unicode characters the same way as the API limit", () => {
  expect(characterMemoLength("声🎙️")).toBe(3);
});

it("keeps an over-limit draft and explains the 2,000 character limit", () => {
  const onChange = vi.fn();
  const value = "あ".repeat(2001);
  render(<CharacterMemoField value={value} onChange={onChange} />);

  const input = screen.getByRole("textbox", { name: "自由メモ（任意）" });
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByRole("alert")).toHaveTextContent("自由メモは2,000文字以内で入力してください。現在2,001文字です。");

  fireEvent.change(input, { target: { value: `${value}追記` } });
  expect(onChange).toHaveBeenCalledWith(`${value}追記`);
});

it("does not report an error at exactly 2,000 characters", () => {
  expect(characterMemoLimitError("あ".repeat(2000))).toBe("");
});

it("reports an over-limit memo inline on its field instead of sending it", () => {
  const report = vi.fn();
  expect(reportCharacterMemoLimit("あ".repeat(2001), report, "profile")).toBe(true);
  expect(report).toHaveBeenCalledWith("自由メモは2,000文字以内で入力してください。現在2,001文字です。", "profile");
  expect(reportCharacterMemoLimit("あ".repeat(2000), report, "profile")).toBe(false);
});
