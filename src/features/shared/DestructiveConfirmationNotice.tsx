import { useEffect } from "react";
import { CenteredNotice } from "./CenteredNotice";
import { cancelDestructiveConfirmation, pendingDestructiveConfirmationKey, useDestructiveConfirmationNotice } from "./destructiveConfirmation";

function sameConfirmationControl(target: EventTarget | null, key: string) {
  return target instanceof Element && target.closest<HTMLElement>("[data-destructive-confirmation-key]")?.dataset.destructiveConfirmationKey === key;
}

export function DestructiveConfirmationNotice() {
  const pending = useDestructiveConfirmationNotice();
  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      const key = pendingDestructiveConfirmationKey();
      if (key && !sameConfirmationControl(event.target, key)) cancelDestructiveConfirmation();
    };
    const onFocusIn = (event: FocusEvent) => {
      const key = pendingDestructiveConfirmationKey();
      if (key && !sameConfirmationControl(event.target, key)) cancelDestructiveConfirmation();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      const key = pendingDestructiveConfirmationKey();
      if (!key) return;
      if (event.key === "Escape") {
        cancelDestructiveConfirmation();
        event.preventDefault();
        event.stopImmediatePropagation();
      } else if (!["Delete", "Backspace"].includes(event.key) && !(["Enter", " "].includes(event.key) && sameConfirmationControl(event.target, key)) && !["Shift", "Control", "Alt", "Meta"].includes(event.key)) {
        cancelDestructiveConfirmation();
      }
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("focusin", onFocusIn, true);
    window.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("focusin", onFocusIn, true);
      window.removeEventListener("keydown", onKeyDown, true);
    };
  }, []);
  if (!pending) return null;
  return (
    <CenteredNotice tone="danger">
      <strong>{pending.prompt}</strong>
      {pending.prompt !== pending.detail && <span>{pending.detail}</span>}
      <small>4秒以内にもう一度{pending.actionLabel}を押すと実行します</small>
    </CenteredNotice>
  );
}
