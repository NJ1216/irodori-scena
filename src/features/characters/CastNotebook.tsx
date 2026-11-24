import { useLayoutEffect, useRef, useState } from "react";
import type { Character } from "../../types";
import { CustomScrollbar } from "../shared/CustomScrollbar";
import { characterSettingEntries, isCompactCharacterSetting, paginateNotebookDetails } from "../shared/studio-utils";
import { CastNotebookDetailsPage, CastNotebookProfilePage } from "./CastNotebookPages";
import { CastNotebookTabs } from "./CastNotebookTabs";
import { castNotebookTabColors, useTabScrollEdges } from "./castNotebookTabState";
import { useNotebookActionSpacer } from "./useNotebookActionSpacer";
import { useCastTabReorder } from "./useCastTabReorder";

export function ScaledDraftCastName({ name }: { name: string }) {
  const containerRef = useRef<HTMLSpanElement | null>(null);
  const textRef = useRef<HTMLSpanElement | null>(null);
  const [scale, setScale] = useState(1);
  useLayoutEffect(() => {
    const container = containerRef.current;
    const text = textRef.current;
    if (!container || !text) return;
    const updateScale = () => {
      setScale(Math.min(1, container.clientWidth / text.scrollWidth));
    };
    updateScale();
    const observer = new ResizeObserver(updateScale);
    observer.observe(container);
    return () => observer.disconnect();
  }, [name]);
  return (
    <span ref={containerRef} className="draft-cast-picker-name">
      <span ref={textRef} className="draft-cast-picker-name-text" style={{ transform: `scaleX(${scale})` }}>
        {name}
      </span>
    </span>
  );
}

export function CastNotebook({
  characters,
  onPlay,
  playingCharacterId,
  onEdit,
  onDelete,
  onViewOriginalAvatar,
  usedCharacterIds = new Set<string>(),
  reorderDisabled = false,
  onReorder = async () => false,
}: {
  characters: Character[];
  onPlay: (character: Character) => void;
  playingCharacterId: string | null;
  onEdit: (character: Character) => void;
  onDelete: (character: Character) => void;
  onViewOriginalAvatar: (character: Character, origin: DOMRect) => void;
  usedCharacterIds?: Set<string>;
  reorderDisabled?: boolean;
  onReorder?: (characterIds: string[]) => Promise<boolean>;
}) {
  const [activeCharacterId, setActiveCharacterId] = useState(characters[0]?.id ?? "");
  const [activeSpread, setActiveSpread] = useState(0);
  const tabsRef = useRef<HTMLElement | null>(null);
  const profilePageRef = useRef<HTMLElement | null>(null);
  const profileContentRef = useRef<HTMLDivElement | null>(null);
  const actionsRef = useRef<HTMLDivElement | null>(null);
  const reorder = useCastTabReorder({ characters, usedIds: usedCharacterIds, disabled: reorderDisabled, tabsRef, onReorder });
  useLayoutEffect(() => {
    tabsRef.current?.scrollTo({ left: 0 });
  });
  const tabScrollEdges = useTabScrollEdges(tabsRef, characters.length);
  const character = characters.find((item) => item.id === activeCharacterId) ?? characters[0];
  const actionSpacerHeight = useNotebookActionSpacer(profilePageRef, profileContentRef, actionsRef, activeCharacterId, activeSpread);
  if (!character) return null;
  const activeCharacterIndex = characters.findIndex((item) => item.id === character.id);
  const activeTabColor = castNotebookTabColors[activeCharacterIndex % castNotebookTabColors.length];

  const settings = characterSettingEntries(character);
  const compactSettings = settings.filter(isCompactCharacterSetting);
  const detailSettings = settings.filter((entry) => !isCompactCharacterSetting(entry));
  const detailPages = paginateNotebookDetails(detailSettings);
  const pageCount = 1 + detailPages.length;
  const spreadCount = Math.ceil(pageCount / 2);
  const visibleSpread = Math.min(activeSpread, spreadCount - 1);
  const firstPageIndex = visibleSpread * 2;
  const renderPage = (pageIndex: number, side: "is-left" | "is-right") => {
    if (pageIndex >= pageCount) {
      return <section className={`cast-notebook-page ${side} is-empty`} />;
    }
    if (pageIndex === 0) {
      return (
        <CastNotebookProfilePage
          side={side}
          character={character}
          playingCharacterId={playingCharacterId}
          compactSettings={compactSettings}
          pageRef={profilePageRef}
          contentRef={profileContentRef}
          actionsRef={actionsRef}
          actionSpacerHeight={actionSpacerHeight}
          onPlay={onPlay}
          onEdit={onEdit}
          onDelete={onDelete}
          onViewOriginalAvatar={onViewOriginalAvatar}
        />
      );
    }
    return <CastNotebookDetailsPage side={side} pageNumber={pageIndex + 1} entries={detailPages[pageIndex - 1]} />;
  };

  return (
    <div className="cast-notebook">
      <CastNotebookTabs
        characters={characters}
        activeCharacterId={character.id}
        usedCharacterIds={usedCharacterIds}
        reorder={reorder}
        reorderDisabled={reorderDisabled}
        tabsRef={tabsRef}
        scrollEdges={tabScrollEdges}
        onSelect={(characterId) => {
          setActiveCharacterId(characterId);
          setActiveSpread(0);
        }}
      />
      <CustomScrollbar targetRef={tabsRef} label="キャスト一覧" placement="flush-outside-end" boundary="window-chrome" />
      <article className={`cast-notebook-spread tab-${activeTabColor}`} aria-live="polite">
        {renderPage(firstPageIndex, "is-left")}
        {renderPage(firstPageIndex + 1, "is-right")}
      </article>
      {spreadCount > 1 && (
        <nav className="cast-notebook-pagination" aria-label="ノートのページ移動">
          <button type="button" aria-label="前の見開き" disabled={visibleSpread === 0} onClick={() => setActiveSpread(visibleSpread - 1)}>
            ‹
          </button>
          <span>
            {firstPageIndex + 1}–{Math.min(firstPageIndex + 2, pageCount)} / {pageCount} ページ
          </span>
          <button type="button" aria-label="次の見開き" disabled={visibleSpread === spreadCount - 1} onClick={() => setActiveSpread(visibleSpread + 1)}>
            ›
          </button>
        </nav>
      )}
    </div>
  );
}
