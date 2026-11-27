import { act, fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { calculateScrollThumb, CustomScrollbar, scrollbarLeft } from "./CustomScrollbar";

describe("calculateScrollThumb", () => {
  it("maps the scroll ratio onto the available thumb travel", () => {
    expect(calculateScrollThumb({ clientHeight: 200, scrollHeight: 1000, scrollTop: 400, trackHeight: 300, minimumThumbLength: 32 })).toEqual({ length: 60, offset: 120 });
  });

  it("uses the minimum thumb and hides a non-scrollable region", () => {
    expect(calculateScrollThumb({ clientHeight: 20, scrollHeight: 1000, scrollTop: 0, trackHeight: 100, minimumThumbLength: 32 })?.length).toBe(32);
    expect(calculateScrollThumb({ clientHeight: 200, scrollHeight: 200, scrollTop: 0, trackHeight: 200, minimumThumbLength: 32 })).toBeNull();
  });
});

describe("scrollbarLeft", () => {
  it("places the custom scrollbar flush against the outside edge", () => {
    expect(scrollbarLeft(300, 14, "flush-outside-end")).toBe(300);
  });
});

describe("CustomScrollbar", () => {
  afterEach(() => vi.useRealTimers());

  function setup() {
    const target = document.createElement("div");
    document.body.append(target);
    Object.defineProperties(target, {
      clientHeight: { value: 200 },
      scrollHeight: { value: 1000 },
      scrollTop: { value: 0, writable: true },
    });
    target.getBoundingClientRect = () => ({ top: 0, bottom: 200, left: 0, right: 300, width: 300, height: 200, x: 0, y: 0, toJSON: () => ({}) });
    target.scrollTo = vi.fn((first?: ScrollToOptions | number, second?: number) => {
      target.scrollTop = typeof first === "number" ? Number(second) : Number(first?.top);
      fireEvent.scroll(target);
    }) as HTMLElement["scrollTo"];
    const targetRef = createRef<HTMLElement>();
    targetRef.current = target;
    render(<CustomScrollbar targetRef={targetRef} label="テスト領域" placement="inset-end" boundary="window-chrome" />);
    return target;
  }

  it("supports keyboard and track paging with accessible values", () => {
    const target = setup();
    const thumb = screen.getByRole("scrollbar", { name: "テスト領域" });
    expect(thumb).toHaveAttribute("aria-valuemax", "800");
    fireEvent.keyDown(thumb, { key: "PageDown" });
    expect(target.scrollTop).toBe(200);
    fireEvent.keyDown(thumb, { key: "End" });
    expect(target.scrollTop).toBe(800);
    fireEvent.pointerDown(thumb.parentElement!.querySelector(".scena-scrollbar-track")!, { clientY: 0 });
    expect(target.scrollTop).toBe(600);
  });

  it("reveals while scrolling and fades after the idle delay", () => {
    vi.useFakeTimers();
    const target = setup();
    const bar = screen.getByRole("scrollbar").parentElement!;
    fireEvent.scroll(target);
    expect(bar).toHaveClass("is-visible");
    act(() => vi.advanceTimersByTime(901));
    expect(bar).not.toHaveClass("is-visible");
  });

  it("follows the target when an ancestor scrolls", () => {
    const target = setup();
    const bar = screen.getByRole("scrollbar").parentElement!;
    expect(bar).toHaveStyle({ top: "0px" });
    target.getBoundingClientRect = () => ({ top: 45, bottom: 245, left: 0, right: 300, width: 300, height: 200, x: 0, y: 45, toJSON: () => ({}) });
    fireEvent.scroll(document);
    expect(bar).toHaveStyle({ top: "45px" });
  });

  it("drags the thumb in proportion to its available travel", () => {
    const target = setup();
    const thumb = screen.getByRole("scrollbar");
    Object.assign(thumb, { setPointerCapture: vi.fn(), releasePointerCapture: vi.fn() });
    const pointerDown = new Event("pointerdown", { bubbles: true, cancelable: true });
    Object.assign(pointerDown, { pointerId: 1, clientY: 0 });
    thumb.dispatchEvent(pointerDown);
    expect(pointerDown.defaultPrevented).toBe(true);
    fireEvent.pointerMove(thumb, { pointerId: 1, clientY: 120 });
    expect(target.scrollTop).toBe(600);
    fireEvent.pointerUp(thumb, { pointerId: 1, clientY: 120 });
    expect(thumb.parentElement).not.toHaveClass("is-dragging");
  });

  it.each(["pointerCancel", "lostPointerCapture"] as const)("ends a thumb drag on %s", (eventName) => {
    const target = setup();
    const thumb = screen.getByRole("scrollbar");
    Object.assign(thumb, { setPointerCapture: vi.fn(), releasePointerCapture: vi.fn() });
    const pointerDown = new Event("pointerdown", { bubbles: true, cancelable: true });
    Object.assign(pointerDown, { pointerId: 1, clientY: 0 });
    act(() => {
      thumb.dispatchEvent(pointerDown);
    });
    expect(thumb.parentElement).toHaveClass("is-dragging");
    fireEvent[eventName](thumb, { pointerId: 1 });
    expect(thumb.parentElement).not.toHaveClass("is-dragging");
    fireEvent.pointerMove(thumb, { pointerId: 1, clientY: 120 });
    expect(target.scrollTop).toBe(0);
  });
});
