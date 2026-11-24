import type { RefObject } from "react";
import { createPortal } from "react-dom";
import type { Character } from "../../types";
import { castNotebookTabColors, castNotebookTabTextures } from "./castNotebookTabState";
import type { useCastTabReorder } from "./useCastTabReorder";

type Reorder = ReturnType<typeof useCastTabReorder>;

function reorderTargetIndex(characters: Character[], usedCharacterIds: Set<string>, drag: NonNullable<Reorder["drag"]>) {
  const remaining = characters.filter((item) => item.id !== drag.character.id);
  const groupEnd = remaining.reduce((end, item, index) => (usedCharacterIds.has(item.id) === usedCharacterIds.has(drag.character.id) ? index + 1 : end), 0);
  return drag.beforeId === null ? groupEnd : remaining.findIndex((item) => item.id === drag.beforeId);
}

export function CastNotebookTabs({
  characters,
  activeCharacterId,
  usedCharacterIds,
  reorder,
  reorderDisabled,
  tabsRef,
  scrollEdges,
  onSelect,
}: {
  characters: Character[];
  activeCharacterId: string;
  usedCharacterIds: Set<string>;
  reorder: Reorder;
  reorderDisabled: boolean;
  tabsRef: RefObject<HTMLElement | null>;
  scrollEdges: { top: boolean; bottom: boolean };
  onSelect: (characterId: string) => void;
}) {
  const dragTargetIndex = reorder.drag ? reorderTargetIndex(characters, usedCharacterIds, reorder.drag) : -1;
  const draggedIndex = reorder.drag ? characters.findIndex((candidate) => candidate.id === reorder.drag!.character.id) : -1;
  return (
    <>
      <nav ref={tabsRef} className={`cast-notebook-tabs scena-scroll-region${scrollEdges.top ? " is-scroll-top" : ""}${scrollEdges.bottom ? " is-scroll-bottom" : ""}${reorder.drag ? " is-reordering" : ""}`} aria-label="キャストを選択">
        {characters.map((item, index) => {
          const isActive = item.id === activeCharacterId;
          const isUsed = usedCharacterIds.has(item.id);
          const isDragged = reorder.drag?.character.id === item.id;
          const shift = reorder.drag ? reorder.drag.height + 5 : 0;
          const translate = index > draggedIndex && index <= dragTargetIndex ? -shift : index >= dragTargetIndex && index < draggedIndex ? shift : 0;
          return (
            <div key={item.id} className={`cast-notebook-tab-slot${isDragged ? " is-placeholder" : ""}`} style={translate ? { transform: `translateY(${translate}px)` } : undefined}>
              <button
                type="button"
                className={`cast-notebook-tab tab-${castNotebookTabColors[index % castNotebookTabColors.length]} texture-${castNotebookTabTextures[index % castNotebookTabTextures.length]}${isActive ? " is-active" : ""}${isUsed ? " is-used" : ""}`}
                aria-current={isActive ? "page" : undefined}
                aria-description={isUsed ? "台本で使用中" : undefined}
                title={item.name}
                data-character-id={item.id}
                disabled={reorderDisabled && Boolean(reorder.drag)}
                onPointerDown={(event) => reorder.pointerDown(event, item)}
                onPointerMove={reorder.pointerMove}
                onPointerUp={(event) => void reorder.pointerUp(event)}
                onPointerCancel={reorder.pointerCancel}
                onClick={(event) => {
                  if (reorder.click(event)) return;
                  onSelect(item.id);
                }}
              >
                <span className="cast-notebook-tab-label">{item.name}</span>
              </button>
            </div>
          );
        })}
      </nav>
      {reorder.drag &&
        createPortal(
          <div className={`${reorder.drag.className} cast-notebook-tab-ghost`} style={{ left: reorder.drag.x + 9, top: reorder.drag.y + 9, width: reorder.drag.width, height: reorder.drag.height }} aria-hidden="true">
            <span className="cast-notebook-tab-label">{reorder.drag.character.name}</span>
          </div>,
          document.body,
        )}
    </>
  );
}
