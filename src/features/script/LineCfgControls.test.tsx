import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DialogueLine } from "../../types";
import { LineCfgControls } from "./LineCfgControls";

const line: DialogueLine = {
  id: "line",
  characterId: "cast",
  text: "台詞",
  stageDirection: "",
  takes: [],
  selectedTakeId: null,
};

describe("LineCfgControls", () => {
  it("keeps arrow-stepped CFG values as drafts until commit", () => {
    const onUpdate = vi.fn();
    const { container } = render(<LineCfgControls line={line} defaults={{ textCfg: 1.5, voiceCfg: 2, captionCfg: 3 }} focused onUpdate={onUpdate} />);
    expect(container.querySelectorAll("svg.line-status-icon")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "行ごとのCFG設定を表示" }));
    expect(container.querySelectorAll("svg.line-status-icon")).toHaveLength(3);
    const inputs = [screen.getByLabelText("発話行ごとのtextCfg（台詞への追従）"), screen.getByLabelText("発話行ごとのvoiceCfg（基準ボイスへの追従）"), screen.getByLabelText("発話行ごとのcaptionCfg（ト書きへの追従）")];
    expect(inputs.map((input) => input.getAttribute("placeholder"))).toEqual(["1.5", "2.0", "3.0"]);
    (inputs[0] as HTMLInputElement).focus();
    fireEvent.keyDown(inputs[0], { key: "ArrowUp" });
    expect(inputs[0]).toHaveValue(1.6);
    fireEvent.keyDown(inputs[0], { key: "ArrowUp" });
    expect(inputs[0]).toHaveValue(1.7);
    expect(onUpdate).not.toHaveBeenCalled();
    (inputs[0] as HTMLInputElement).blur();
    expect(onUpdate).toHaveBeenCalledExactlyOnceWith({ textCfg: 1.7 });
    (inputs[1] as HTMLInputElement).focus();
    fireEvent.keyDown(inputs[1], { key: "ArrowDown" });
    expect(onUpdate).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(inputs[1], { key: "Enter" });
    expect(onUpdate).toHaveBeenNthCalledWith(2, { voiceCfg: 1.9 });
  });

  it("keeps draft input untouched and validates only when committed", () => {
    const onUpdate = vi.fn();
    render(<LineCfgControls line={{ ...line, textCfg: 4.2 }} defaults={{ textCfg: 3, voiceCfg: 5, captionCfg: 3 }} focused onUpdate={onUpdate} />);
    expect(screen.queryByLabelText("発話行ごとのvoiceCfg（基準ボイスへの追従）")).not.toBeInTheDocument();
    const input = screen.getByLabelText("発話行ごとのtextCfg（台詞への追従）");
    fireEvent.change(input, { target: { value: "12" } });
    expect(input).toHaveValue(12);
    expect(onUpdate).not.toHaveBeenCalled();
    fireEvent.blur(input);
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(onUpdate).not.toHaveBeenCalled();
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.blur(input);
    expect(onUpdate).toHaveBeenCalledWith({ textCfg: undefined });
  });

  it("collapses on line focus loss and keeps only configured values visible", () => {
    const onUpdate = vi.fn();
    const props = { line: { ...line, textCfg: 4.2 }, defaults: { textCfg: 3, voiceCfg: 5, captionCfg: 3 }, onUpdate };
    const { rerender } = render(<LineCfgControls {...props} focused />);
    fireEvent.click(screen.getByRole("button", { name: "行ごとのCFG設定を表示" }));
    expect(screen.getByLabelText("発話行ごとのvoiceCfg（基準ボイスへの追従）")).toBeInTheDocument();
    rerender(<LineCfgControls {...props} focused={false} />);
    expect(screen.queryByLabelText("発話行ごとのvoiceCfg（基準ボイスへの追従）")).not.toBeInTheDocument();
    expect(screen.getByLabelText("発話行ごとのtextCfg（台詞への追従）")).toHaveValue(4.2);
  });

  it("commits a selected-line arrow draft once on blur", () => {
    const onAdjustSelected = vi.fn();
    const onPreviewSelected = vi.fn();
    const onSetSelected = vi.fn();
    const onUpdate = vi.fn();
    render(<LineCfgControls line={line} defaults={{ textCfg: 1.5, voiceCfg: 2, captionCfg: 3 }} focused onUpdate={onUpdate} onAdjustSelected={onAdjustSelected} onSetSelected={onSetSelected} onPreviewSelected={onPreviewSelected} />);
    const disclosure = screen.getByRole("button", { name: "行ごとのCFG設定を表示" });
    expect(disclosure).toHaveAttribute("data-preserve-line-selection", "true");
    fireEvent.click(disclosure);
    const input = screen.getByLabelText("発話行ごとのtextCfg（台詞への追従）");
    expect(input).toHaveAttribute("data-preserve-line-selection", "true");
    fireEvent.keyDown(input, { key: "ArrowUp" });
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(onPreviewSelected).toHaveBeenNthCalledWith(1, "textCfg", [1]);
    expect(onPreviewSelected).toHaveBeenNthCalledWith(2, "textCfg", [1, 1]);
    expect(onAdjustSelected).not.toHaveBeenCalled();
    expect(onSetSelected).not.toHaveBeenCalled();
    expect(onUpdate).not.toHaveBeenCalled();
    fireEvent.blur(input);
    expect(onPreviewSelected).toHaveBeenLastCalledWith("textCfg", null);
    expect(onAdjustSelected).toHaveBeenCalledExactlyOnceWith("textCfg", [1, 1]);
    expect(onSetSelected).not.toHaveBeenCalled();
    expect(onUpdate).not.toHaveBeenCalled();
    expect(input).toHaveValue(1.7);
  });

  it("commits a value or reset to all selected lines with the primary modifier and Enter", () => {
    const onSetSelected = vi.fn();
    const onUpdate = vi.fn();
    render(<LineCfgControls line={line} defaults={{ textCfg: 1.5, voiceCfg: 2, captionCfg: 3 }} focused onUpdate={onUpdate} onSetSelected={onSetSelected} />);
    fireEvent.click(screen.getByRole("button", { name: "行ごとのCFG設定を表示" }));
    const input = screen.getByLabelText("発話行ごとのtextCfg（台詞への追従）");
    fireEvent.change(input, { target: { value: "4.5" } });
    fireEvent.keyDown(input, { key: "Enter", metaKey: true });
    expect(onSetSelected).toHaveBeenNthCalledWith(1, "textCfg", 4.5);

    fireEvent.change(input, { target: { value: "" } });
    fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
    expect(onSetSelected).toHaveBeenNthCalledWith(2, "textCfg", undefined);
    fireEvent.blur(input);
    expect(onUpdate).not.toHaveBeenCalled();
  });
});
