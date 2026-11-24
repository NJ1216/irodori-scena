import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";
import { insertIntoLineEditorAtRange, type LineTextEditorElement } from "./EmojiTextArea";
import { caretMarkerRect, editorCaretRangeAtPoint } from "./editorSelection";

const START_DISTANCE = 5;
const EDGE_SIZE = 52;
const EDGE_SPEED = 14;

type DropTarget = { editor: LineTextEditorElement; range: Range; rect: DOMRect };
type DragState = { pointerId: number; emoji: string; startX: number; startY: number; active: boolean };
type GhostState = { emoji: string; x: number; y: number };

function targetAtPoint(x: number, y: number): DropTarget | null {
  const editor = document.elementFromPoint(x, y)?.closest<LineTextEditorElement>(".script-canvas .line-text-editor");
  if (!editor) return null;
  const range = editorCaretRangeAtPoint(editor, x, y);
  return range ? { editor, range, rect: caretMarkerRect(editor, range, x) } : null;
}

function clearTarget(target: DropTarget | null) {
  target?.editor.classList.remove("is-emoji-drop-target");
}

export function useEmojiPaletteDrag(enabled: boolean, hideTooltip: () => void) {
  const drag = useRef<DragState | null>(null);
  const target = useRef<DropTarget | null>(null);
  const pointer = useRef({ x: 0, y: 0 });
  const scrollFrame = useRef<number | null>(null);
  const suppressClick = useRef(false);
  const [ghost, setGhost] = useState<GhostState | null>(null);
  const [marker, setMarker] = useState<DOMRect | null>(null);

  const stopScroll = () => {
    if (scrollFrame.current !== null) cancelAnimationFrame(scrollFrame.current);
    scrollFrame.current = null;
  };
  const updateTarget = () => {
    const next = targetAtPoint(pointer.current.x, pointer.current.y);
    if (target.current?.editor !== next?.editor) {
      clearTarget(target.current);
      next?.editor.classList.add("is-emoji-drop-target");
    }
    target.current = next;
    setMarker(next?.rect ?? null);
  };
  const autoScroll = () => {
    const canvas = document.querySelector<HTMLElement>(".script-canvas");
    if (!canvas || !drag.current?.active) return stopScroll();
    const rect = canvas.getBoundingClientRect();
    const inside = pointer.current.x >= rect.left && pointer.current.x <= rect.right && pointer.current.y >= rect.top && pointer.current.y <= rect.bottom;
    const speed = !inside ? 0 : pointer.current.y < rect.top + EDGE_SIZE ? -EDGE_SPEED : pointer.current.y > rect.bottom - EDGE_SIZE ? EDGE_SPEED : 0;
    if (speed) canvas.scrollTop += speed;
    updateTarget();
    scrollFrame.current = requestAnimationFrame(autoScroll);
  };
  const cancel = () => {
    stopScroll();
    clearTarget(target.current);
    target.current = null;
    drag.current = null;
    document.documentElement.classList.remove("is-dragging-expression-emoji");
    setGhost(null);
    setMarker(null);
  };
  const finish = (commit: boolean) => {
    const destination = target.current;
    const current = drag.current;
    if (commit && current?.active && destination) insertIntoLineEditorAtRange(destination.editor, current.emoji, destination.range);
    cancel();
  };

  useEffect(() => {
    const keydown = (event: KeyboardEvent) => event.key === "Escape" && finish(false);
    const blur = () => finish(false);
    window.addEventListener("keydown", keydown);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("keydown", keydown);
      window.removeEventListener("blur", blur);
      cancel();
    };
    // Gesture callbacks intentionally own their initial refs until unmount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handlersFor = (emoji: string) => {
    if (!enabled) return {};
    return {
      onPointerDown: (event: ReactPointerEvent<HTMLButtonElement>) => {
        if (event.button !== 0) return;
        suppressClick.current = false;
        drag.current = { pointerId: event.pointerId, emoji, startX: event.clientX, startY: event.clientY, active: false };
        event.currentTarget.setPointerCapture?.(event.pointerId);
      },
      onPointerMove: (event: ReactPointerEvent<HTMLButtonElement>) => {
        const current = drag.current;
        if (!current || current.pointerId !== event.pointerId) return;
        pointer.current = { x: event.clientX, y: event.clientY };
        if (!current.active && Math.hypot(event.clientX - current.startX, event.clientY - current.startY) < START_DISTANCE) return;
        if (!current.active) {
          current.active = true;
          hideTooltip();
          document.documentElement.classList.add("is-dragging-expression-emoji");
          scrollFrame.current = requestAnimationFrame(autoScroll);
        }
        event.preventDefault();
        setGhost({ emoji: current.emoji, x: event.clientX, y: event.clientY });
        updateTarget();
      },
      onPointerUp: (event: ReactPointerEvent<HTMLButtonElement>) => {
        if (drag.current?.pointerId !== event.pointerId) return;
        suppressClick.current = drag.current.active;
        if (drag.current.active) event.preventDefault();
        finish(true);
      },
      onPointerCancel: () => finish(false),
      onClickCapture: (event: ReactMouseEvent<HTMLButtonElement>) => {
        if (!suppressClick.current) return;
        suppressClick.current = false;
        event.preventDefault();
        event.stopPropagation();
      },
    };
  };

  const overlay =
    enabled && (ghost || marker)
      ? createPortal(
          <>
            {ghost && (
              <div className="emoji-drag-ghost" style={{ left: ghost.x, top: ghost.y }} aria-hidden="true">
                {ghost.emoji}
              </div>
            )}
            {marker && <div className="emoji-drop-caret" style={{ left: marker.left, top: marker.top, height: marker.height }} aria-hidden="true" />}
          </>,
          document.body,
        )
      : null;
  return { handlersFor, overlay };
}
