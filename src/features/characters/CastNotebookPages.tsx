import { useLayoutEffect, useRef, useState, type RefObject } from "react";
import type { Character } from "../../types";
import { useDestructiveConfirmation } from "../shared/destructiveConfirmation";
import { avatarImageUrl, compactCharacterSettingWidthClass } from "../shared/studio-utils";

function ScaledCastNotebookSettingValue({ value }: { value: string }) {
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
  }, [value]);
  return (
    <span ref={containerRef} className="cast-notebook-compact-value">
      <span ref={textRef} className="cast-notebook-compact-value-text" style={{ transform: `scaleX(${scale})` }}>
        {value}
      </span>
    </span>
  );
}

function CastNotebookActions({ character, onEdit, onDelete, actionsRef }: { character: Character; onEdit: (character: Character) => void; onDelete: (character: Character) => void; actionsRef: RefObject<HTMLDivElement | null> }) {
  const confirmingDelete = useDestructiveConfirmation(`delete-character-${character.id}`);
  return (
    <div ref={actionsRef} className="cast-notebook-actions">
      <button type="button" className="link-button" onClick={() => onEdit(character)}>
        ✎ 設定を編集
      </button>
      <button type="button" className={`delete-button ${confirmingDelete ? "is-confirming" : ""}`} data-destructive-confirmation-key={`delete-character-${character.id}`} onClick={() => onDelete(character)}>
        削除
      </button>
    </div>
  );
}

function CastNotebookAvatar({ character, onViewOriginalAvatar }: { character: Character; onViewOriginalAvatar: (character: Character, origin: DOMRect) => void }) {
  const thumbnailUrl = character.avatarThumbnailUrl ?? character.avatarUrl;
  if (character.avatarOriginalUrl) {
    return (
      <button type="button" className="cast-notebook-avatar-button" aria-label={`${character.name}の原画像を表示`} onClick={(event) => onViewOriginalAvatar(character, event.currentTarget.getBoundingClientRect())}>
        <div className="cast-notebook-avatar has-image">
          <img src={avatarImageUrl(thumbnailUrl ?? "", character.avatarVersion)} alt={`${character.name}の画像`} />
        </div>
      </button>
    );
  }
  return <div className={`cast-notebook-avatar${thumbnailUrl ? " has-image" : ""}`}>{thumbnailUrl ? <img src={avatarImageUrl(thumbnailUrl, character.avatarVersion)} alt={`${character.name}の画像`} /> : character.name.slice(0, 1)}</div>;
}

type NotebookSide = "is-left" | "is-right";

export function CastNotebookProfilePage({
  side,
  character,
  playingCharacterId,
  compactSettings,
  pageRef,
  contentRef,
  actionsRef,
  actionSpacerHeight,
  onPlay,
  onEdit,
  onDelete,
  onViewOriginalAvatar,
}: {
  side: NotebookSide;
  character: Character;
  playingCharacterId: string | null;
  compactSettings: [string, string][];
  pageRef: RefObject<HTMLElement | null>;
  contentRef: RefObject<HTMLDivElement | null>;
  actionsRef: RefObject<HTMLDivElement | null>;
  actionSpacerHeight: number;
  onPlay: (character: Character) => void;
  onEdit: (character: Character) => void;
  onDelete: (character: Character) => void;
  onViewOriginalAvatar: (character: Character, origin: DOMRect) => void;
}) {
  return (
    <section ref={pageRef} className={`cast-notebook-page ${side}`}>
      <div ref={contentRef} className="cast-notebook-profile-content">
        <div className="cast-notebook-identity">
          <div>
            <p className="eyebrow">CAST PROFILE</p>
            <div className="cast-notebook-name-row">
              <h2>{character.name}</h2>
              <button
                type="button"
                className="cast-notebook-reference-voice"
                aria-label={playingCharacterId === character.id ? `${character.name}の参照ボイスを停止` : `${character.name}の参照ボイスを再生`}
                aria-pressed={playingCharacterId === character.id}
                title={playingCharacterId === character.id ? "参照ボイスを停止" : "参照ボイスを再生"}
                onClick={() => onPlay(character)}
              >
                {playingCharacterId === character.id ? "■" : "▶"}
              </button>
            </div>
          </div>
          <CastNotebookAvatar character={character} onViewOriginalAvatar={onViewOriginalAvatar} />
        </div>
        {compactSettings.length > 0 ? (
          <dl className={`cast-notebook-settings is-compact compact-count-${Math.min(compactSettings.length, 3)}`}>
            {compactSettings.map(([label, value]) => (
              <div key={label} className={compactCharacterSettingWidthClass(value)}>
                <dt>{label}</dt>
                <dd>
                  <ScaledCastNotebookSettingValue value={value} />
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="cast-notebook-empty-summary">プロフィールの基本情報はまだありません。</p>
        )}
      </div>
      <div className="cast-notebook-action-spacer" style={{ height: actionSpacerHeight }} />
      <CastNotebookActions actionsRef={actionsRef} character={character} onDelete={onDelete} onEdit={onEdit} />
    </section>
  );
}

export function CastNotebookDetailsPage({ side, pageNumber, entries }: { side: NotebookSide; pageNumber: number; entries: [string, string][] }) {
  return (
    <section className={`cast-notebook-page ${side}`}>
      <p className="eyebrow">{pageNumber === 2 ? "DETAILS" : "DETAILS · CONTINUED"}</p>
      {entries.length > 0 ? (
        <dl className="cast-notebook-settings is-details">
          {entries.map(([label, value], index) => (
            <div key={`${label}-${index}`}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="cast-notebook-empty-details">詳しい設定はまだありません。</p>
      )}
    </section>
  );
}
