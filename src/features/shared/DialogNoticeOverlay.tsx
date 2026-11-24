import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CenteredNotice } from "./CenteredNotice";

const OPEN_DIALOG_SELECTOR = '.modal-backdrop, [aria-modal="true"]';

type ShownNotice = { text: string; serial: number };

/**
 * Repeats a studio notice above open dialogs, where the header notice area is hidden behind the backdrop.
 * Progress notices raised while work runs (busy) stay in the header so they never cover a dialog's own controls.
 */
export function DialogNoticeOverlay({ text, serial, busy = false }: { text: string; serial: number; busy?: boolean }) {
  const [shown, setShown] = useState<ShownNotice | null>(null);
  const handledSerial = useRef(serial);
  const closeButton = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const visible = shown !== null;
  useEffect(() => {
    if (serial === handledSerial.current) return;
    handledSerial.current = serial;
    if (busy) return;
    const dialogOpen = Boolean(text.trim()) && document.querySelector(OPEN_DIALOG_SELECTOR) !== null;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- whether a dialog is open is only known from the DOM after the notice commits.
    setShown(dialogOpen ? { text, serial } : null);
  }, [busy, serial, text]);
  useLayoutEffect(() => {
    if (!visible) return;
    const previous = document.activeElement;
    returnFocus.current = previous instanceof HTMLElement && previous !== document.body ? previous : null;
    closeButton.current?.focus({ preventScroll: true });
    return () => {
      if (returnFocus.current?.isConnected) returnFocus.current.focus({ preventScroll: true });
    };
  }, [visible]);
  useEffect(() => {
    if (!visible) return;
    const closeWithEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      setShown(null);
    };
    window.addEventListener("keydown", closeWithEscape, true);
    return () => window.removeEventListener("keydown", closeWithEscape, true);
  }, [visible]);
  if (!shown) return null;
  return createPortal(
    <>
      <div className="notice-overlay-scrim" aria-hidden="true" onClick={() => setShown(null)} />
      <CenteredNotice tone="neutral" label="通知" interactive>
        <p className="notice-overlay-text">{shown.text}</p>
        <button ref={closeButton} type="button" className="button-secondary notice-overlay-close" aria-label="通知を閉じる" onClick={() => setShown(null)}>
          閉じる
        </button>
      </CenteredNotice>
    </>,
    document.body,
  );
}
