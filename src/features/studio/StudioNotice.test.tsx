// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StudioNotice } from "./StudioNotice";

describe("StudioNotice", () => {
  it("releases character animation layers while preserving the completed message", () => {
    const { container } = render(<StudioNotice busy={null} text="準備完了" cancellable={false} onCancel={vi.fn()} />);
    const characters = container.querySelectorAll(".notice-character");
    // React selects the prefixed event in jsdom, which lacks AnimationEvent.
    const eventName = "AnimationEvent" in window ? "animationend" : "webkitAnimationEnd";
    characters.forEach((character) => fireEvent(character, new Event(eventName, { bubbles: true })));
    expect([...characters].every((character) => character.classList.contains("is-settled"))).toBe(true);
    expect(container.querySelector(".notice-screen-reader-text")).toHaveTextContent("準備完了");
  });

  it("shows the right-side cancel action only for a cancellable selected-line task", () => {
    const cancel = vi.fn();
    const { rerender } = render(<StudioNotice busy="generate-selected-lines" text="生成中です…" cancellable onCancel={cancel} />);
    fireEvent.click(screen.getByRole("button", { name: "生成をキャンセル" }));
    expect(cancel).toHaveBeenCalledOnce();

    rerender(<StudioNotice busy="line-1" text="自動生成中です…" cancellable={false} onCancel={cancel} />);
    expect(screen.queryByRole("button", { name: "生成をキャンセル" })).toBeNull();
  });
});
