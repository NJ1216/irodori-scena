import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Character } from "../../types";
import { CastNotebook } from "./CastNotebook";

const character = (index: number): Character => ({
  id: `character-${index}`,
  name: `キャスト ${index}`,
  profile: "",
  voiceKeywords: "",
  referenceAudioUrl: `/media/character-${index}.wav`,
  referenceFile: `character-${index}.wav`,
  createdAt: index,
});

describe("CastNotebook", () => {
  let observerCount = 0;

  beforeEach(() => {
    observerCount = 0;
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor() {
          observerCount += 1;
        }
        observe() {}
        disconnect() {}
      },
    );
    Object.defineProperty(HTMLElement.prototype, "scrollTo", { configurable: true, value: vi.fn() });
    Object.defineProperty(HTMLElement.prototype, "scrollBy", { configurable: true, value: vi.fn() });
    Object.defineProperty(HTMLElement.prototype, "setPointerCapture", { configurable: true, value: vi.fn() });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete (HTMLElement.prototype as Partial<HTMLElement>).scrollTo;
    delete (HTMLElement.prototype as Partial<HTMLElement>).scrollBy;
    delete (HTMLElement.prototype as Partial<HTMLElement>).setPointerCapture;
  });

  it.each([10, 50, 100])("does not add a layout observer for each of %i cast tabs", (count) => {
    const characters = Array.from({ length: count }, (_, index) => character(index + 1));
    const view = render(<CastNotebook characters={characters} onPlay={vi.fn()} playingCharacterId={null} onEdit={vi.fn()} onDelete={vi.fn()} onViewOriginalAvatar={vi.fn()} />);

    expect(screen.getByRole("navigation", { name: "キャストを選択" }).querySelectorAll(".cast-notebook-tab")).toHaveLength(count);
    expect(screen.getByRole("button", { name: `キャスト ${count}` })).toHaveAttribute("title", `キャスト ${count}`);
    expect(observerCount).toBe(2);
    expect(screen.getByRole("navigation", { name: "キャストを選択" })).toHaveClass("scena-scroll-region");
    view.unmount();
  });

  it("marks only casts used in the script", () => {
    render(<CastNotebook characters={[character(1), character(2)]} usedCharacterIds={new Set(["character-2"])} onPlay={vi.fn()} playingCharacterId={null} onEdit={vi.fn()} onDelete={vi.fn()} onViewOriginalAvatar={vi.fn()} />);

    expect(screen.getByRole("button", { name: "キャスト 1" })).not.toHaveClass("is-used");
    expect(screen.getByRole("button", { name: "キャスト 1" })).not.toHaveAttribute("aria-description");
    expect(screen.getByRole("button", { name: "キャスト 2" })).toHaveClass("is-used");
    expect(screen.getByRole("button", { name: "キャスト 2" })).toHaveAttribute("aria-description", "台本で使用中");
  });

  it("keeps a short pointer movement as selection", () => {
    render(<CastNotebook characters={[character(1), character(2)]} usedCharacterIds={new Set(["character-1", "character-2"])} onReorder={vi.fn()} onPlay={vi.fn()} playingCharacterId={null} onEdit={vi.fn()} onDelete={vi.fn()} onViewOriginalAvatar={vi.fn()} />);
    const second = screen.getByRole("button", { name: "キャスト 2" });
    fireEvent.pointerDown(second, { pointerId: 1, button: 0, clientX: 10, clientY: 50 });
    fireEvent.pointerMove(second, { pointerId: 1, clientX: 13, clientY: 53 });
    fireEvent.pointerUp(second, { pointerId: 1 });
    fireEvent.click(second);
    expect(second).toHaveAttribute("aria-current", "page");
    expect(document.querySelector(".cast-notebook-tab-ghost")).toBeNull();
  });

  it("shows only a same-sized blank and matching ghost, then saves the dropped order", async () => {
    const onReorder = vi.fn().mockResolvedValue(true);
    render(<CastNotebook characters={[character(1), character(2), character(3)]} usedCharacterIds={new Set(["character-1", "character-2", "character-3"])} onReorder={onReorder} onPlay={vi.fn()} playingCharacterId={null} onEdit={vi.fn()} onDelete={vi.fn()} onViewOriginalAvatar={vi.fn()} />);
    const first = screen.getByRole("button", { name: "キャスト 1" });
    const second = screen.getByRole("button", { name: "キャスト 2" });
    const third = screen.getByRole("button", { name: "キャスト 3" });
    vi.spyOn(first, "getBoundingClientRect").mockReturnValue({ top: 10, bottom: 42, left: 0, right: 100, width: 100, height: 32, x: 0, y: 10, toJSON: () => ({}) });
    vi.spyOn(second, "getBoundingClientRect").mockReturnValue({ top: 50, bottom: 82, left: 0, right: 100, width: 100, height: 32, x: 0, y: 50, toJSON: () => ({}) });
    Object.defineProperty(second, "offsetHeight", { configurable: true, value: 32 });
    vi.spyOn(third, "getBoundingClientRect").mockReturnValue({ top: 90, bottom: 122, left: 0, right: 100, width: 100, height: 32, x: 0, y: 90, toJSON: () => ({}) });
    Object.defineProperty(third, "offsetHeight", { configurable: true, value: 32 });
    fireEvent.pointerDown(first, { pointerId: 2, button: 0, clientX: 10, clientY: 20 });
    fireEvent.pointerMove(first, { pointerId: 2, clientX: 12, clientY: 70 });
    const ghost = document.querySelector(".cast-notebook-tab-ghost");
    expect(ghost).toHaveTextContent("キャスト 1");
    expect(ghost).toHaveClass("tab-rose", "texture-grain", "is-active", "is-used");
    expect(document.querySelectorAll(".cast-notebook-tab-slot.is-placeholder")).toHaveLength(1);
    expect(second.closest(".cast-notebook-tab-slot")).toHaveStyle({ transform: "translateY(-37px)" });
    expect(document.querySelector(".cast-notebook-drop-line")).toBeNull();
    fireEvent.pointerUp(first, { pointerId: 2 });
    await waitFor(() => expect(onReorder).toHaveBeenCalledWith(["character-2", "character-1", "character-3"]));
    expect(screen.getByRole("button", { name: "キャスト 1" })).toHaveAttribute("aria-current", "page");
  });

  it("cancels on Escape and disables dragging while unavailable", () => {
    const onReorder = vi.fn();
    const { rerender } = render(<CastNotebook characters={[character(1), character(2)]} usedCharacterIds={new Set(["character-1", "character-2"])} onReorder={onReorder} onPlay={vi.fn()} playingCharacterId={null} onEdit={vi.fn()} onDelete={vi.fn()} onViewOriginalAvatar={vi.fn()} />);
    const first = screen.getByRole("button", { name: "キャスト 1" });
    fireEvent.pointerDown(first, { pointerId: 3, button: 0, clientX: 0, clientY: 0 });
    fireEvent.pointerMove(first, { pointerId: 3, clientX: 20, clientY: 20 });
    expect(document.querySelector(".cast-notebook-tab-ghost")).not.toBeNull();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(document.querySelector(".cast-notebook-tab-ghost")).toBeNull();
    expect(onReorder).not.toHaveBeenCalled();
    rerender(<CastNotebook characters={[character(1), character(2)]} reorderDisabled usedCharacterIds={new Set(["character-1", "character-2"])} onReorder={onReorder} onPlay={vi.fn()} playingCharacterId={null} onEdit={vi.fn()} onDelete={vi.fn()} onViewOriginalAvatar={vi.fn()} />);
    fireEvent.pointerDown(screen.getByRole("button", { name: "キャスト 1" }), { pointerId: 4, button: 0, clientX: 0, clientY: 0 });
    fireEvent.pointerMove(screen.getByRole("button", { name: "キャスト 1" }), { pointerId: 4, clientX: 20, clientY: 20 });
    expect(document.querySelector(".cast-notebook-tab-ghost")).toBeNull();
  });

  it.each(["pointerCancel", "blur"])("does not save when a drag ends through %s", (ending) => {
    const onReorder = vi.fn();
    render(<CastNotebook characters={[character(1), character(2)]} usedCharacterIds={new Set(["character-1", "character-2"])} onReorder={onReorder} onPlay={vi.fn()} playingCharacterId={null} onEdit={vi.fn()} onDelete={vi.fn()} onViewOriginalAvatar={vi.fn()} />);
    const first = document.querySelector<HTMLButtonElement>('[data-character-id="character-1"]')!;
    fireEvent.pointerDown(first, { pointerId: 8, button: 0, clientX: 0, clientY: 0 });
    fireEvent.pointerMove(first, { pointerId: 8, clientX: 20, clientY: 60 });
    if (ending === "pointerCancel") fireEvent.pointerCancel(first, { pointerId: 8 });
    else fireEvent.blur(window);
    expect(onReorder).not.toHaveBeenCalled();
    expect(document.querySelector(".cast-notebook-tab-ghost")).toBeNull();
  });

  it("continues when pointer capture fails and commits only once", async () => {
    const onReorder = vi.fn().mockResolvedValue(false);
    Object.defineProperty(HTMLElement.prototype, "setPointerCapture", {
      configurable: true,
      value: vi.fn(() => {
        throw new Error("unsupported");
      }),
    });
    render(<CastNotebook characters={[character(1), character(2)]} usedCharacterIds={new Set(["character-1", "character-2"])} onReorder={onReorder} onPlay={vi.fn()} playingCharacterId={null} onEdit={vi.fn()} onDelete={vi.fn()} onViewOriginalAvatar={vi.fn()} />);
    const first = document.querySelector<HTMLButtonElement>('[data-character-id="character-1"]')!;
    const second = document.querySelector<HTMLButtonElement>('[data-character-id="character-2"]')!;
    vi.spyOn(second, "getBoundingClientRect").mockReturnValue({ top: 10, width: 100, height: 32 } as DOMRect);
    Object.defineProperty(second, "offsetHeight", { configurable: true, value: 32 });
    fireEvent.pointerDown(first, { pointerId: 9, button: 0, clientX: 0, clientY: 0 });
    fireEvent.pointerMove(first, { pointerId: 9, clientX: 10, clientY: 100 });
    fireEvent.pointerUp(first, { pointerId: 9 });
    fireEvent.pointerUp(window, { pointerId: 9 });
    await waitFor(() => expect(onReorder).toHaveBeenCalledTimes(1));
  });
});
