/* eslint-disable react-hooks/refs, react-refresh/only-export-components -- Imperative scroll ownership is synchronized at explicit DOM event boundaries. */
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type PointerEvent, type RefObject } from "react";
import { observeResizeAfterLayout } from "./observeResizeAfterLayout";

export type ScrollbarPlacement = "inset-end" | "outside-end" | "flush-outside-end" | "viewport-end";
export type ScrollbarBoundary = "window-chrome" | "dialog-chrome";

export type ScrollMetrics = {
  clientHeight: number;
  scrollHeight: number;
  scrollTop: number;
  trackHeight: number;
  minimumThumbLength: number;
};

export function calculateScrollThumb({ clientHeight, scrollHeight, scrollTop, trackHeight, minimumThumbLength }: ScrollMetrics) {
  if (clientHeight <= 0 || scrollHeight <= clientHeight || trackHeight <= 0) return null;
  const length = Math.min(trackHeight, Math.max(minimumThumbLength, (clientHeight / scrollHeight) * trackHeight));
  const travel = Math.max(0, trackHeight - length);
  const maximumScroll = scrollHeight - clientHeight;
  return { length, offset: maximumScroll > 0 ? (scrollTop / maximumScroll) * travel : 0 };
}

type Bounds = { top: number; left: number; height: number; zIndex?: number };

function numericToken(name: string, fallback: number) {
  const value = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue(name));
  return Number.isFinite(value) ? value : fallback;
}

export function scrollbarLeft(targetRight: number, hitWidth: number, placement: ScrollbarPlacement) {
  if (placement === "viewport-end") return window.innerWidth - hitWidth;
  if (placement === "flush-outside-end") return targetRight;
  const inset = placement === "outside-end" ? -((numericToken("--scena-space-5", 24) + hitWidth) / 2) : numericToken("--scena-scrollbar-gutter-inset", 3);
  return targetRight - hitWidth - inset;
}

function scrollbarBounds(target: HTMLElement, boundary: ScrollbarBoundary, placement: ScrollbarPlacement): Bounds {
  const targetRect = target.getBoundingClientRect();
  const hitWidth = numericToken("--scena-scrollbar-hit-width", 14);
  const dialog = boundary === "dialog-chrome" ? target.closest<HTMLElement>(".modal") : null;
  const header = boundary === "dialog-chrome" ? dialog?.querySelector<HTMLElement>(".dialog-header") : document.querySelector<HTMLElement>(".app-header");
  const footer = boundary === "dialog-chrome" ? dialog?.querySelector<HTMLElement>(".dialog-footer") : document.querySelector<HTMLElement>(".main-window-footer");
  const top = Math.max(targetRect.top, header?.getBoundingClientRect().bottom ?? targetRect.top);
  const bottom = Math.min(targetRect.bottom, footer?.getBoundingClientRect().top ?? targetRect.bottom);
  const left = scrollbarLeft(targetRect.right, hitWidth, placement);
  const backdrop = dialog?.closest<HTMLElement>(".modal-backdrop");
  const backdropLayer = backdrop ? Number.parseInt(getComputedStyle(backdrop).zIndex, 10) || 100 : undefined;
  return { top, left, height: Math.max(0, bottom - top), zIndex: backdropLayer ? backdropLayer + 1 : undefined };
}

export function CustomScrollbar({ targetRef, label, placement, boundary }: { targetRef: RefObject<HTMLElement | null>; label: string; placement: ScrollbarPlacement; boundary: ScrollbarBoundary }) {
  const generatedId = useId().replaceAll(":", "");
  const [bounds, setBounds] = useState<Bounds | null>(null);
  const [thumb, setThumb] = useState<{ length: number; offset: number } | null>(null);
  const [visible, setVisible] = useState(false);
  const hideTimer = useRef<number | null>(null);
  const dragging = useRef<{ pointerId: number; startY: number; startScrollTop: number } | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const reveal = useCallback((persistent = false) => {
    setVisible(true);
    if (hideTimer.current !== null) window.clearTimeout(hideTimer.current);
    if (!persistent) hideTimer.current = window.setTimeout(() => setVisible(false), numericToken("--scena-scrollbar-fade-delay", 900));
  }, []);
  const endDrag = (event: PointerEvent<HTMLElement>) => {
    if (dragging.current?.pointerId !== event.pointerId) return;
    dragging.current = null;
    setIsDragging(false);
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    reveal();
  };
  const dragEndHandlers = { onPointerUp: endDrag, onPointerCancel: endDrag, onLostPointerCapture: endDrag };
  const update = useCallback(() => {
    const target = targetRef.current;
    if (!target) return;
    if (!target.id) target.id = `scena-scroll-region-${generatedId}`;
    const nextBounds = scrollbarBounds(target, boundary, placement);
    setBounds(nextBounds);
    setThumb(
      calculateScrollThumb({
        clientHeight: target.clientHeight,
        scrollHeight: target.scrollHeight,
        scrollTop: target.scrollTop,
        trackHeight: nextBounds.height,
        minimumThumbLength: numericToken("--scena-scrollbar-thumb-min", 32),
      }),
    );
  }, [boundary, generatedId, placement, targetRef]);

  useLayoutEffect(() => update(), [update]);
  useEffect(() => {
    const target = targetRef.current;
    if (!target) return;
    const onScroll = () => {
      update();
      reveal();
    };
    const onWheel = () => reveal();
    target.addEventListener("scroll", onScroll, { passive: true });
    target.addEventListener("wheel", onWheel, { passive: true });
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    const stopObservingResize = observeResizeAfterLayout(update, [target]);
    const mutationObserver = new MutationObserver(update);
    mutationObserver.observe(target, { childList: true, subtree: true, characterData: true });
    return () => {
      target.removeEventListener("scroll", onScroll);
      target.removeEventListener("wheel", onWheel);
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
      stopObservingResize();
      mutationObserver.disconnect();
      if (hideTimer.current !== null) window.clearTimeout(hideTimer.current);
    };
  }, [reveal, targetRef, update]);

  if (!bounds || !thumb) return null;
  const target = targetRef.current;
  const maximum = target ? Math.max(0, target.scrollHeight - target.clientHeight) : 0;
  const moveBy = (amount: number) => target?.scrollTo({ top: Math.max(0, Math.min(maximum, target.scrollTop + amount)), behavior: "auto" });
  return (
    <div className={`scena-scrollbar${visible ? " is-visible" : ""}${isDragging ? " is-dragging" : ""}`} style={{ top: bounds.top, left: bounds.left, height: bounds.height, zIndex: bounds.zIndex }} onPointerEnter={() => reveal(true)} onPointerLeave={() => !dragging.current && reveal()}>
      <div
        className="scena-scrollbar-track"
        onPointerDown={(event) => {
          if (event.target !== event.currentTarget || !target) return;
          event.preventDefault();
          const thumbTop = bounds.top + thumb.offset;
          moveBy(event.clientY < thumbTop ? -target.clientHeight : target.clientHeight);
          reveal();
        }}
      />
      <div
        role="scrollbar"
        tabIndex={0}
        aria-label={label}
        aria-controls={target?.id}
        aria-orientation="vertical"
        aria-valuemin={0}
        aria-valuemax={maximum}
        aria-valuenow={Math.round(target?.scrollTop ?? 0)}
        className="scena-scrollbar-thumb"
        style={{ height: thumb.length, transform: `translateY(${thumb.offset}px)` }}
        onFocus={() => reveal(true)}
        onBlur={() => reveal()}
        onKeyDown={(event) => {
          if (!target) return;
          const amounts: Record<string, number> = { ArrowUp: -40, ArrowDown: 40, PageUp: -target.clientHeight, PageDown: target.clientHeight, Home: -maximum, End: maximum };
          if (!(event.key in amounts)) return;
          event.preventDefault();
          if (event.key === "Home") target.scrollTo({ top: 0 });
          else if (event.key === "End") target.scrollTo({ top: maximum });
          else moveBy(amounts[event.key]);
          reveal(true);
        }}
        onPointerDown={(event) => {
          if (!target) return;
          event.preventDefault();
          event.currentTarget.setPointerCapture(event.pointerId);
          dragging.current = { pointerId: event.pointerId, startY: event.clientY, startScrollTop: target.scrollTop };
          setIsDragging(true);
          reveal(true);
        }}
        onPointerMove={(event) => {
          if (!target || dragging.current?.pointerId !== event.pointerId) return;
          const travel = bounds.height - thumb.length;
          if (travel > 0) target.scrollTop = dragging.current.startScrollTop + ((event.clientY - dragging.current.startY) / travel) * maximum;
        }}
        {...dragEndHandlers}
      />
    </div>
  );
}
