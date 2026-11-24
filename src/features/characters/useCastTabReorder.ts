/* eslint-disable react-hooks/set-state-in-effect -- availability changes cancel an in-progress pointer interaction. */
import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent, type RefObject } from "react";
import type { Character } from "../../types";

const DRAG_THRESHOLD = 5,
  AUTO_SCROLL_EDGE = 36;
export type CastTabDrag = { character: Character; beforeId: string | null; x: number; y: number; width: number; height: number; className: string };
type Origin = { character: Character; pointerId: number; x: number; y: number; element: HTMLButtonElement; className: string; width: number; height: number; active: boolean };

export function useCastTabReorder({ characters, usedIds, disabled, tabsRef, onReorder }: { characters: Character[]; usedIds: Set<string>; disabled: boolean; tabsRef: RefObject<HTMLElement | null>; onReorder: (ids: string[]) => Promise<boolean> }) {
  const [drag, setDrag] = useState<CastTabDrag | null>(null);
  const origin = useRef<Origin | null>(null),
    dragRef = useRef<CastTabDrag | null>(null),
    suppressClick = useRef(false),
    committing = useRef(false);
  const clear = () => {
    origin.current = null;
    dragRef.current = null;
    setDrag(null);
  };
  const cancel = () => clear();
  const beforeAt = (draggedId: string, clientY: number) => {
    const sameGroup = characters.filter((item) => item.id !== draggedId && usedIds.has(item.id) === usedIds.has(draggedId));
    for (const item of sameGroup) {
      const element = tabsRef.current?.querySelector<HTMLButtonElement>(`[data-character-id="${CSS.escape(item.id)}"]`);
      if (element && clientY < element.getBoundingClientRect().top + element.offsetHeight / 2) return item.id;
    }
    return null;
  };
  const finish = async (commit: boolean, pointerId?: number) => {
    const start = origin.current;
    if (!start || (pointerId !== undefined && start.pointerId !== pointerId)) return;
    const current = dragRef.current;
    clear();
    if (!commit || !current || committing.current) return;
    const remaining = characters.filter((item) => item.id !== current.character.id);
    const groupEnd = remaining.reduce((end, item, index) => (usedIds.has(item.id) === usedIds.has(current.character.id) ? index + 1 : end), 0);
    const target = current.beforeId === null ? groupEnd : remaining.findIndex((item) => item.id === current.beforeId);
    remaining.splice(target, 0, current.character);
    const ids = remaining.map((item) => item.id);
    if (ids.every((id, index) => characters[index]?.id === id)) return;
    committing.current = true;
    try {
      await onReorder(ids);
    } finally {
      committing.current = false;
    }
  };
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => event.key === "Escape" && void finish(false);
    const blur = () => void finish(false),
      visibility = () => document.hidden && void finish(false);
    const pointerup = (event: PointerEvent) => void finish(true, event.pointerId);
    window.addEventListener("keydown", keydown);
    window.addEventListener("blur", blur);
    window.addEventListener("pointerup", pointerup);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      window.removeEventListener("keydown", keydown);
      window.removeEventListener("blur", blur);
      window.removeEventListener("pointerup", pointerup);
      document.removeEventListener("visibilitychange", visibility);
      cancel();
    };
    // The gesture owns the character snapshot and save callback until it ends.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (!disabled) return;
    origin.current = null;
    dragRef.current = null;
    setDrag(null);
  }, [disabled]);
  const pointerDown = (event: ReactPointerEvent<HTMLButtonElement>, character: Character) => {
    if (disabled || event.button !== 0 || committing.current) return;
    const rect = event.currentTarget.getBoundingClientRect();
    origin.current = { character, pointerId: event.pointerId, x: event.clientX, y: event.clientY, element: event.currentTarget, className: event.currentTarget.className, width: rect.width, height: rect.height, active: false };
    suppressClick.current = false;
  };
  const pointerMove = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const start = origin.current;
    if (!start || start.pointerId !== event.pointerId) return;
    if (!start.active && Math.hypot(event.clientX - start.x, event.clientY - start.y) <= DRAG_THRESHOLD) return;
    if (!start.active) {
      start.active = true;
      try {
        start.element.setPointerCapture?.(event.pointerId);
      } catch {
        /* root events remain usable */
      }
    }
    event.preventDefault();
    suppressClick.current = true;
    const next = { character: start.character, beforeId: beforeAt(start.character.id, event.clientY), x: event.clientX, y: event.clientY, width: start.width, height: start.height, className: start.className };
    dragRef.current = next;
    setDrag(next);
    const tabs = tabsRef.current;
    if (tabs) {
      const bounds = tabs.getBoundingClientRect();
      if (event.clientY < bounds.top + AUTO_SCROLL_EDGE) tabs.scrollBy({ top: -12 });
      else if (event.clientY > bounds.bottom - AUTO_SCROLL_EDGE) tabs.scrollBy({ top: 12 });
    }
  };
  const click = (event: ReactMouseEvent) => {
    if (!suppressClick.current) return false;
    suppressClick.current = false;
    event.preventDefault();
    event.stopPropagation();
    return true;
  };
  return { drag, pointerDown, pointerMove, pointerUp: (event: ReactPointerEvent<HTMLButtonElement>) => finish(true, event.pointerId), pointerCancel: () => void finish(false), click };
}
