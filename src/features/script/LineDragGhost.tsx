import { useLayoutEffect, useRef } from "react";
import { visibleDragGhostCardCount } from "./lineReorder";
import type { LineDragGhostState } from "./useLineReorderDrag";

export function LineDragGhost({ ghost }: { ghost: LineDragGhostState | null }) {
  const previewRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (!ghost || !previewRef.current) return;
    const preview = ghost.preview.cloneNode(true) as HTMLElement;
    preview.classList.remove("is-focused", "is-selected", "is-line-drag-source", "is-line-drop-target", "is-line-drop-expanded");
    preview.setAttribute("data-drag-ghost-card", "true");
    previewRef.current.replaceChildren(preview);
  }, [ghost]);
  if (!ghost) return null;
  const cardCount = visibleDragGhostCardCount(ghost.count);
  return (
    <div className="line-drag-ghost" style={{ left: ghost.x, top: ghost.y, width: ghost.width }} aria-hidden="true">
      {Array.from({ length: cardCount - 1 }, (_, index) => cardCount - index - 1).map((layer) => (
        <div key={layer} className={`line-drag-ghost-silhouette is-layer-${layer}`} data-drag-ghost-card="true" />
      ))}
      <div ref={previewRef} className="line-drag-ghost-preview" />
    </div>
  );
}
