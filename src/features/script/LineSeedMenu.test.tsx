// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DialogueLine } from "../../types";
import { LineSeedMenu } from "./LineSeedMenu";

const line = (patch: Partial<DialogueLine> = {}): DialogueLine => ({
  id: "line-1",
  characterId: "cast-1",
  text: "台詞",
  stageDirection: "",
  takes: [],
  selectedTakeId: null,
  ...patch,
});

describe("LineSeedMenu", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("opens immediately on hover, fixes the displayed seed, and preserves pointer selection", () => {
    const onUpdate = vi.fn();
    render(<LineSeedMenu line={line()} displayedSeed={42} generating={false} onUpdate={onUpdate} onGenerateWithSeed={vi.fn()} onNotice={vi.fn()} />);
    fireEvent.pointerEnter(screen.getByRole("button", { name: "Seed 42" }).parentElement!);
    expect(screen.getByRole("menu")).toBeVisible();
    fireEvent.click(screen.getByRole("menuitem", { name: "seed値を固定" }));
    expect(onUpdate).toHaveBeenCalledWith({ fixedSeed: 42 });
    expect(screen.getByRole("button", { name: "Seed 42" })).toHaveAttribute("data-preserve-line-selection", "true");
  });

  it("opens from a keyboard click", () => {
    render(<LineSeedMenu line={line()} displayedSeed={42} generating={false} onUpdate={vi.fn()} onGenerateWithSeed={vi.fn()} onNotice={vi.fn()} />);
    const trigger = screen.getByRole("button", { name: "Seed 42" });
    fireEvent.click(trigger);
    expect(screen.getByRole("menu")).toBeVisible();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("offers release for a fixed seed and closes with Escape or an outside pointer", () => {
    const onUpdate = vi.fn();
    render(<LineSeedMenu line={line({ fixedSeed: 7 })} displayedSeed={99} generating={false} onUpdate={onUpdate} onGenerateWithSeed={vi.fn()} onNotice={vi.fn()} />);
    const trigger = screen.getByRole("button", { name: "Seed 99 固定中" });
    fireEvent.focus(trigger);
    expect(screen.getByRole("menuitem", { name: "seed値の固定を解除" })).toBeVisible();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    fireEvent.focus(trigger);
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    fireEvent.focus(trigger);
    fireEvent.click(screen.getByRole("menuitem", { name: "seed値の固定を解除" }));
    expect(onUpdate).toHaveBeenCalledWith({ fixedSeed: undefined, manualSeed: undefined });
  });

  it("adds a Take with the entered seed only at the explicit commit boundary", async () => {
    const onUpdate = vi.fn();
    const onGenerateWithSeed = vi.fn().mockResolvedValue(true);
    const onNotice = vi.fn();
    render(<LineSeedMenu line={line()} displayedSeed={42} generating={false} onUpdate={onUpdate} onGenerateWithSeed={onGenerateWithSeed} onNotice={onNotice} />);
    fireEvent.focus(screen.getByRole("button", { name: "Seed 42" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "seed値でtakeを追加" }));
    const input = screen.getByRole("textbox", { name: "Seed値" });
    fireEvent.change(input, { target: { value: "-" } });
    expect(onUpdate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "takeを追加" }));
    expect(onNotice).toHaveBeenCalledWith("Seedは0〜1999999999の整数で入力してください");
    expect(input).toHaveValue("-");
    fireEvent.change(input, { target: { value: "123456" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await vi.waitFor(() => expect(onGenerateWithSeed).toHaveBeenCalledWith(123456));
    expect(onUpdate).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(screen.queryByRole("textbox", { name: "Seed値" })).not.toBeInTheDocument());
  });

  it("keeps the entered seed open when Take generation fails", async () => {
    const onGenerateWithSeed = vi.fn().mockResolvedValue(false);
    render(<LineSeedMenu line={line()} displayedSeed={42} generating={false} onUpdate={vi.fn()} onGenerateWithSeed={onGenerateWithSeed} onNotice={vi.fn()} />);
    fireEvent.focus(screen.getByRole("button", { name: "Seed 42" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "seed値でtakeを追加" }));
    const input = screen.getByRole("textbox", { name: "Seed値" });
    fireEvent.change(input, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "takeを追加" }));
    await vi.waitFor(() => expect(onGenerateWithSeed).toHaveBeenCalledWith(123456));
    await vi.waitFor(() => expect(screen.getByRole("button", { name: "takeを追加" })).toBeEnabled());
    expect(input).toHaveValue("123456");
  });

  it("copies the displayed seed and reports clipboard failures without changing the fixed value", async () => {
    const onNotice = vi.fn();
    const onUpdate = vi.fn();
    const writeText = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error("denied"));
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const { rerender } = render(<LineSeedMenu line={line({ fixedSeed: 7 })} displayedSeed={99} generating={true} onUpdate={onUpdate} onGenerateWithSeed={vi.fn()} onNotice={onNotice} />);
    fireEvent.focus(screen.getByRole("button", { name: "Seed 99 固定中" }));
    expect(screen.getByRole("menuitem", { name: "seed値の固定を解除" })).toBeDisabled();
    fireEvent.click(screen.getByRole("menuitem", { name: "seed値をコピー" }));
    await vi.waitFor(() => expect(onNotice).toHaveBeenCalledWith("Seed 99 をコピーしました"));
    rerender(<LineSeedMenu line={line({ fixedSeed: 7 })} displayedSeed={100} generating={false} onUpdate={onUpdate} onGenerateWithSeed={vi.fn()} onNotice={onNotice} />);
    fireEvent.focus(screen.getByRole("button", { name: "Seed 100 固定中" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "seed値をコピー" }));
    await vi.waitFor(() => expect(onNotice).toHaveBeenCalledWith("Seedをコピーできませんでした"));
    expect(writeText).toHaveBeenNthCalledWith(1, "99");
    expect(writeText).toHaveBeenNthCalledWith(2, "100");
    expect(onUpdate).not.toHaveBeenCalled();
  });
});
