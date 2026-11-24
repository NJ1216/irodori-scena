import { useLayoutEffect, useRef } from "react";

function focusable(dialog: HTMLElement) {
  return Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]'));
}

/** Contain this nested portal while preserving the parent editor and its drafts. */
export function useLoraRegisterFocus(busy: boolean, completed: boolean, restoreSelector?: string) {
  const dialogRef = useRef<HTMLFormElement>(null);
  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const backdrop = dialog.closest(".modal-backdrop");
    const background = Array.from(document.body.children).filter((node) => node !== backdrop && node instanceof HTMLElement);
    const previousInert = background.map((node) => ({ node, inert: node.hasAttribute("inert") }));
    for (const { node } of previousInert) node.setAttribute("inert", "");
    const focusFirst = () => (focusable(dialog)[0] ?? dialog).focus();
    const containFocus = (event: FocusEvent) => {
      if (!dialog.contains(event.target as Node)) focusFirst();
    };
    const containTab = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const elements = focusable(dialog),
        first = elements[0],
        last = elements.at(-1);
      if (!first || !last) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const outside = !dialog.contains(document.activeElement);
      if (outside || document.activeElement === dialog || (event.shiftKey ? document.activeElement === first : document.activeElement === last)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    };
    document.addEventListener("focusin", containFocus, true);
    document.addEventListener("keydown", containTab, true);
    focusFirst();
    return () => {
      document.removeEventListener("focusin", containFocus, true);
      document.removeEventListener("keydown", containTab, true);
      for (const { node, inert } of previousInert) {
        if (!inert) node.removeAttribute("inert");
      }
      if (restoreSelector) document.querySelector<HTMLElement>(restoreSelector)?.focus();
      else if (trigger?.isConnected) trigger.focus();
    };
  }, [restoreSelector]);
  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (busy) dialog.focus();
    else if (completed || document.activeElement === dialog) (focusable(dialog)[0] ?? dialog).focus();
  }, [busy, completed]);
  return dialogRef;
}
