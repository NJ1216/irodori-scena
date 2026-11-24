import { useRef, type FocusEvent, type MouseEvent, type PointerEvent } from "react";
import type { LineSelectionModifiers } from "./linePointerSelection";

export function useLineCardFocus({ selected, rewriteActionPersistent, onFocusLine }: { selected: boolean; rewriteActionPersistent: boolean; onFocusLine: (modifiers?: LineSelectionModifiers) => void }) {
  const pointerFocusHandled = useRef(false);
  return {
    onPointerDown(event: PointerEvent<HTMLElement>) {
      pointerFocusHandled.current = false;
      if (event.shiftKey || event.altKey) {
        event.preventDefault();
        pointerFocusHandled.current = true;
        onFocusLine({ shiftKey: event.shiftKey, altKey: event.altKey });
      }
    },
    onFocusCapture(event: FocusEvent<HTMLElement>) {
      if ((event.target as HTMLElement).closest(".line-rewrite-action")) return;
      if (pointerFocusHandled.current) return;
      if (selected && rewriteActionPersistent && event.target === event.currentTarget) return;
      if (event.currentTarget.dataset.shortcutFocus === "true") {
        delete event.currentTarget.dataset.shortcutFocus;
        return;
      }
      pointerFocusHandled.current = true;
      onFocusLine({ shiftKey: false, altKey: false, preserveSelection: selected && (event.target as HTMLElement).matches("[data-preserve-line-selection='true']") });
    },
    onClick(event: MouseEvent<HTMLElement>) {
      if ((event.target as HTMLElement).closest("input, textarea, select, button, [contenteditable='true']")) {
        pointerFocusHandled.current = false;
        return;
      }
      if (!pointerFocusHandled.current) onFocusLine();
      pointerFocusHandled.current = false;
    },
  };
}
