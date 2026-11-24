import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const TOOLTIP_DELAY_MS = 80;

type TooltipState = { label: string; x: number; y: number; below: boolean; adjusted: boolean };

function titledElement(target: EventTarget | null) {
  return target instanceof Element ? target.closest<HTMLElement>("[data-scena-tooltip], [title]") : null;
}

/** Shared tooltip: title uses a short delay; data-scena-tooltip displays immediately. */
export function QuickTooltip() {
  const activeRef = useRef<HTMLElement | null>(null);
  const tooltipRef = useRef<HTMLSpanElement | null>(null);
  const labelRef = useRef("");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  useLayoutEffect(() => {
    const element = tooltipRef.current;
    if (!element || tooltip?.adjusted) return;
    const bounds = element.getBoundingClientRect();
    const inset = 12;
    const correction = bounds.left < inset ? inset - bounds.left : bounds.right > window.innerWidth - inset ? window.innerWidth - inset - bounds.right : 0;
    setTooltip((current) => (current ? { ...current, x: current.x + correction, adjusted: true } : current));
  }, [tooltip]);

  useEffect(() => {
    const hide = () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      timerRef.current = null;
      const active = activeRef.current;
      if (active?.isConnected && !active.hasAttribute("data-scena-tooltip") && labelRef.current && !active.hasAttribute("title")) active.setAttribute("title", labelRef.current);
      activeRef.current = null;
      labelRef.current = "";
      setTooltip(null);
    };
    const show = (element: HTMLElement) => {
      if (activeRef.current === element) return;
      hide();
      const immediate = element.hasAttribute("data-scena-tooltip");
      const label = (element.getAttribute("data-scena-tooltip") ?? element.getAttribute("title"))?.trim();
      if (!label) return;
      const rect = element.getBoundingClientRect();
      activeRef.current = element;
      labelRef.current = label;
      element.removeAttribute("title");
      const publish = () => {
        const below = rect.top < 44;
        setTooltip({ label, x: rect.left + rect.width / 2, y: below ? rect.bottom : rect.top, below, adjusted: false });
      };
      if (immediate) publish();
      else timerRef.current = setTimeout(publish, TOOLTIP_DELAY_MS);
    };
    const onMouseOver = (event: MouseEvent) => {
      const element = titledElement(event.target);
      if (element) show(element);
    };
    const onMouseOut = (event: MouseEvent) => {
      const active = activeRef.current;
      if (active && event.relatedTarget instanceof Node && active.contains(event.relatedTarget)) return;
      hide();
    };
    const onFocusIn = (event: FocusEvent) => {
      const element = titledElement(event.target);
      if (element) show(element);
    };
    const onFocusOut = () => hide();
    document.addEventListener("mouseover", onMouseOver, true);
    document.addEventListener("mouseout", onMouseOut, true);
    document.addEventListener("focusin", onFocusIn, true);
    document.addEventListener("focusout", onFocusOut, true);
    window.addEventListener("scroll", hide, true);
    return () => {
      hide();
      document.removeEventListener("mouseover", onMouseOver, true);
      document.removeEventListener("mouseout", onMouseOut, true);
      document.removeEventListener("focusin", onFocusIn, true);
      document.removeEventListener("focusout", onFocusOut, true);
      window.removeEventListener("scroll", hide, true);
    };
  }, []);

  return tooltip
    ? createPortal(
        <span ref={tooltipRef} className={`quick-tooltip${tooltip.below ? " is-below" : ""}`} style={{ left: tooltip.x, top: tooltip.y }} role="tooltip">
          {tooltip.label}
        </span>,
        document.body,
      )
    : null;
}
