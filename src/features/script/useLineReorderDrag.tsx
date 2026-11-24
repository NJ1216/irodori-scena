import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent, type RefObject } from "react";
import type { StudioProject } from "../../types";
import type { LineDropTarget } from "./lineReorder";
import { movableLineIds } from "./lineReorder";

const START_DISTANCE = 5,
  EDGE_SIZE = 52,
  EDGE_SPEED = 14;
const INTERACTIVE = "input, textarea, select, button, a, [contenteditable='true'], .line-result-status, .line-meta-item";
type Boundary = LineDropTarget & { element: HTMLElement; append: boolean };
type Drag = { pointerId: number; startX: number; startY: number; lineId: string; ids: string[]; preview: HTMLElement; width: number; active: boolean };
export type LineDragGhostState = { x: number; y: number; count: number; preview: HTMLElement; width: number };

function sameBoundary(left: Boundary | null, right: Boundary | null) {
  return left?.sceneId === right?.sceneId && left?.beforeLineId === right?.beforeLineId;
}

function boundaryAt(root: HTMLElement, x: number, y: number): Boundary | null {
  const scenes = Array.from(root.querySelectorAll<HTMLElement>(".scene-box[data-scene-id]"));
  const scene = scenes.find((item) => {
    const rect = item.getBoundingClientRect();
    return y >= rect.top && y <= rect.bottom && x >= rect.left && x <= rect.right;
  });
  if (!scene?.dataset.sceneId) return null;
  const heads = Array.from(scene.querySelectorAll<HTMLElement>(".line-card:not(.is-cue-member), .line-card.is-cue-head")).sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
  const before = heads.find((item) => y < item.getBoundingClientRect().top + item.getBoundingClientRect().height / 2);
  const stack = scene.querySelector<HTMLElement>(".line-stack");
  if (!stack) return null;
  const beforeLineId = before?.dataset.lineId;
  const zones = Array.from(scene.querySelectorAll<HTMLElement>(".line-insert-zone[data-line-drop-before]"));
  const zone = zones.find((item) => item.dataset.lineDropBefore === (beforeLineId ?? ""));
  if (zone) return { sceneId: scene.dataset.sceneId, beforeLineId, element: zone, append: !beforeLineId };
  return before ? { sceneId: scene.dataset.sceneId, beforeLineId, element: before.closest<HTMLElement>(".virtual-scene-cue") ?? before, append: false } : { sceneId: scene.dataset.sceneId, element: stack, append: true };
}

function useLineDragRefs() {
  return {
    rootRef: useRef<HTMLElement>(null),
    drag: useRef<Drag | null>(null),
    boundary: useRef<Boundary | null>(null),
    scrollFrame: useRef<number | null>(null),
    suppressClick: useRef(false),
  };
}

function useDragCancellation(dragRef: RefObject<Drag | null>, rootRef: RefObject<HTMLElement | null>, finish: (commit: boolean) => void, cancel: () => void) {
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => event.key === "Escape" && finish(false);
    const blur = () => finish(false);
    const selectstart = (event: Event) => {
      if (dragRef.current && event.target instanceof Node && rootRef.current?.contains(event.target)) event.preventDefault();
    };
    window.addEventListener("keydown", keydown);
    window.addEventListener("blur", blur);
    document.addEventListener("selectstart", selectstart);
    return () => {
      window.removeEventListener("keydown", keydown);
      window.removeEventListener("blur", blur);
      document.removeEventListener("selectstart", selectstart);
      cancel();
    };
    // The active gesture owns its project snapshot and callbacks until it ends.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

export function useLineReorderDrag({ project, selectedLineIds, onSelect, onMove }: { project: StudioProject; selectedLineIds: string[]; onSelect: (ids: string[], focusedId: string) => void; onMove: (ids: string[], target: LineDropTarget) => void }) {
  const { rootRef, drag: dragRef, boundary: boundaryRef, scrollFrame: scrollFrameRef, suppressClick: suppressClickRef } = useLineDragRefs();
  const pointer = useRef({ x: 0, y: 0 });
  const [ghost, setGhost] = useState<LineDragGhostState | null>(null);
  const clearBoundary = () => {
    const current = boundaryRef.current;
    if (current) {
      current.element.classList.remove("is-line-drop-target", "is-line-drop-append");
    }
    boundaryRef.current = null;
  };
  const setBoundary = (next: Boundary | null) => {
    if (sameBoundary(boundaryRef.current, next)) return;
    clearBoundary();
    if (!next) return;
    boundaryRef.current = next;
    next.element.classList.add("is-line-drop-target");
    if (next.append) next.element.classList.add("is-line-drop-append");
  };
  const stopScroll = () => {
    if (scrollFrameRef.current !== null) cancelAnimationFrame(scrollFrameRef.current);
    scrollFrameRef.current = null;
  };
  const cancel = () => {
    stopScroll();
    clearBoundary();
    document.documentElement.classList.remove("is-reordering-lines");
    rootRef.current?.classList.remove("is-line-dragging");
    dragRef.current = null;
    setGhost(null);
  };
  const autoScroll = () => {
    const root = rootRef.current;
    const current = dragRef.current;
    if (!root || !current?.active) return stopScroll();
    const rect = root.getBoundingClientRect();
    const speed = pointer.current.y < rect.top + EDGE_SIZE ? -EDGE_SPEED : pointer.current.y > rect.bottom - EDGE_SIZE ? EDGE_SPEED : 0;
    if (speed) root.scrollTop += speed;
    setBoundary(boundaryAt(root, pointer.current.x, pointer.current.y));
    scrollFrameRef.current = requestAnimationFrame(autoScroll);
  };

  const finish = (commit: boolean) => {
    const current = dragRef.current;
    const target = boundaryRef.current;
    if (commit && current?.active && target) onMove(current.ids, { sceneId: target.sceneId, beforeLineId: target.beforeLineId });
    cancel();
  };

  useDragCancellation(dragRef, rootRef, finish, cancel);

  const onPointerDown = (event: ReactPointerEvent<HTMLElement>) => {
    if (event.button !== 0 || !(event.target instanceof Element) || event.target.closest(INTERACTIVE)) return;
    const card = event.target.closest<HTMLElement>(".line-card[data-line-id]");
    if (!card?.dataset.lineId) return;
    const ids = movableLineIds(project, card.dataset.lineId, selectedLineIds);
    const firstCard = rootRef.current?.querySelector<HTMLElement>(`.line-card[data-line-id='${CSS.escape(ids[0])}']`) ?? card;
    const cardBounds = card.getBoundingClientRect();
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      lineId: card.dataset.lineId,
      ids,
      preview: firstCard.cloneNode(true) as HTMLElement,
      width: cardBounds.width,
      active: false,
    };
    document.documentElement.classList.add("is-reordering-lines");
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLElement>) => {
    const current = dragRef.current;
    if (!current || current.pointerId !== event.pointerId) return;
    window.getSelection()?.removeAllRanges();
    pointer.current = { x: event.clientX, y: event.clientY };
    if (!current.active && Math.hypot(event.clientX - current.startX, event.clientY - current.startY) < START_DISTANCE) return;
    if (!current.active) {
      current.active = true;
      event.currentTarget.setPointerCapture(event.pointerId);
      onSelect(current.ids, current.lineId);
      rootRef.current?.classList.add("is-line-dragging");
      setGhost({ x: event.clientX, y: event.clientY, count: current.ids.length, preview: current.preview, width: current.width });
      scrollFrameRef.current = requestAnimationFrame(autoScroll);
    } else setGhost((value) => (value ? { ...value, x: event.clientX, y: event.clientY } : value));
    event.preventDefault();
    setBoundary(boundaryAt(event.currentTarget, event.clientX, event.clientY));
  };

  const onPointerUp = (event: ReactPointerEvent<HTMLElement>) => {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    suppressClickRef.current = Boolean(dragRef.current.active);
    if (dragRef.current.active) event.preventDefault();
    finish(true);
  };

  return {
    rootRef,
    handlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp,
      onPointerCancel: () => finish(false),
      onClickCapture: (event: ReactMouseEvent<HTMLElement>) => {
        if (!suppressClickRef.current) return;
        suppressClickRef.current = false;
        event.preventDefault();
        event.stopPropagation();
      },
    },
    ghost,
  };
}
