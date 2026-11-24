import { type KeyboardEvent, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { getPopoverPlacement } from "./modelSelectionPlacement";
import type { Placement } from "./modelSelectionTypes";

const CLOSE_DELAY = 160;

function usePopoverPlacement(open: boolean, itemCount: number, triggerRef: React.RefObject<HTMLButtonElement | null>) {
  const [placement, setPlacement] = useState<Placement>({ left: 0, top: 0, width: 320, cardWidth: 320, maxHeight: 320, above: false });
  useLayoutEffect(() => {
    if (!open) return;
    const position = () => {
      const trigger = triggerRef.current;
      if (!trigger) return;
      const anchor = trigger.getBoundingClientRect();
      const preferredCardWidth = Number.parseFloat(getComputedStyle(trigger).getPropertyValue("--scena-model-popover-card-width")) || anchor.width;
      setPlacement(getPopoverPlacement(anchor, itemCount, preferredCardWidth));
    };
    position();
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, true);
    return () => {
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", position, true);
    };
  }, [itemCount, open, triggerRef]);
  return placement;
}

function useDismissOnOutsideOrEscape(open: boolean, setOpen: (value: boolean) => void, triggerRef: React.RefObject<HTMLButtonElement | null>, popoverId: string, suppressFocusOpen: React.MutableRefObject<boolean>) {
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!triggerRef.current?.contains(target) && !document.getElementById(popoverId)?.contains(target)) setOpen(false);
    };
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        suppressFocusOpen.current = true;
        window.requestAnimationFrame(() => triggerRef.current?.focus());
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open, setOpen, triggerRef, popoverId, suppressFocusOpen]);
}

export function useModelSelectionPopover(itemCount: number, triggerRef: React.RefObject<HTMLButtonElement | null>) {
  const [open, setOpen] = useState(false);
  const closeTimer = useRef<number | null>(null);
  const clickCanClose = useRef(false);
  const suppressFocusOpen = useRef(false);
  const popoverId = useId();
  const placement = usePopoverPlacement(open, itemCount, triggerRef);

  const cancelClose = () => {
    if (closeTimer.current != null) window.clearTimeout(closeTimer.current);
    closeTimer.current = null;
  };
  const scheduleClose = () => {
    cancelClose();
    closeTimer.current = window.setTimeout(() => setOpen(false), CLOSE_DELAY);
  };
  const close = (restoreFocus = false) => {
    cancelClose();
    setOpen(false);
    if (restoreFocus) {
      suppressFocusOpen.current = true;
      window.requestAnimationFrame(() => triggerRef.current?.focus());
    }
  };
  const focusOption = (direction: 1 | -1) => {
    const buttons = Array.from(document.getElementById(popoverId)?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);
    if (!buttons.length) return;
    const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
    buttons[(current + direction + buttons.length) % buttons.length].focus();
  };
  useDismissOnOutsideOrEscape(open, setOpen, triggerRef, popoverId, suppressFocusOpen);
  useEffect(() => () => cancelClose(), []);

  const triggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
    event.preventDefault();
    setOpen(true);
    window.requestAnimationFrame(() => focusOption(event.key === "ArrowDown" ? 1 : -1));
  };
  const optionKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowRight") {
      event.preventDefault();
      focusOption(1);
    }
    if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
      event.preventDefault();
      focusOption(-1);
    }
  };
  const triggerPointerEnter = () => {
    clickCanClose.current = false;
    setOpen(true);
  };
  const triggerFocus = () => {
    if (suppressFocusOpen.current) suppressFocusOpen.current = false;
    else setOpen(true);
  };
  const triggerClick = () => {
    if (clickCanClose.current) setOpen((value) => !value);
    else {
      clickCanClose.current = true;
      setOpen(true);
    }
  };
  const view = { open, placement, popoverId, cancelClose, scheduleClose, close, optionKeyDown, triggerKeyDown, triggerPointerEnter, triggerFocus, triggerClick };
  return view;
}
