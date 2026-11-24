import { useLayoutEffect, useRef } from "react";
import type { Character, ScriptCastContext } from "../../types";
import { characterSettingEntries, isCompactCharacterSetting, NOTEBOOK_RULE_HEIGHT } from "../shared/studio-utils";
import { ScriptCastAvatar } from "./ScriptCastAvatar";
import { useDestructiveConfirmation } from "../shared/destructiveConfirmation";

function scriptCastDescription(context?: ScriptCastContext) {
  return context?.description || context?.setting || "";
}

function SpeakerCardActions({
  character,
  onPlay,
  playingReference,
  onEdit,
  onEditScriptContext,
  onDelete,
}: {
  character: Character;
  onPlay: (character: Character) => void;
  playingReference: boolean;
  onEdit?: (character: Character) => void;
  onEditScriptContext?: (character: Character) => void;
  onDelete?: (character: Character) => void;
}) {
  const confirmingDelete = useDestructiveConfirmation(`delete-character-${character.id}`);
  const label = playingReference ? "参照ボイスを停止" : "参照ボイスを再生";
  const icon = playingReference ? "■" : "▶";
  return (
    <div className="speaker-card-actions">
      {onEditScriptContext && (
        <button className="script-cast-context-edit" aria-label="台本上の設定を編集" onClick={() => onEditScriptContext(character)}>
          Edit
        </button>
      )}
      <button className={onEditScriptContext ? "reference-voice-button" : "link-button"} aria-label={label} aria-pressed={playingReference} title={label} onClick={() => onPlay(character)}>
        {icon}
        {!onEditScriptContext && " 参照ボイス"}
      </button>
      {onEdit && (
        <button className="link-button" onClick={() => onEdit(character)}>
          ✎ 設定を編集
        </button>
      )}
      {onDelete && (
        <button className={`delete-button ${confirmingDelete ? "is-confirming" : ""}`} onClick={() => onDelete(character)}>
          削除
        </button>
      )}
    </div>
  );
}

export function SpeakerCard({
  character,
  onPlay,
  playingReference,
  onEdit,
  onEditScriptContext,
  onDelete,
  detailed = false,
  scriptContext,
}: {
  character: Character;
  onPlay: (character: Character) => void;
  playingReference?: boolean;
  onEdit?: (character: Character) => void;
  onDelete?: (character: Character) => void;
  detailed?: boolean;
  scriptContext?: ScriptCastContext;
  onEditScriptContext?: (character: Character) => void;
}) {
  const settings = detailed ? characterSettingEntries(character) : [];
  const compactSettings = settings.filter(isCompactCharacterSetting);
  const detailSettings = settings.filter((entry) => !isCompactCharacterSetting(entry));
  const description = scriptCastDescription(scriptContext);
  const role = scriptContext?.role?.trim() || "";
  const showRole = !["", "登場人物", character.name.trim()].includes(role);
  const cardRef = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    if (!detailed || !cardRef.current) return;
    const card = cardRef.current;
    const snapHeightToRules = () => {
      card.style.height = "auto";
      const borderHeight = card.offsetHeight - card.clientHeight;
      const snappedHeight = Math.ceil((card.scrollHeight + borderHeight) / NOTEBOOK_RULE_HEIGHT) * NOTEBOOK_RULE_HEIGHT;
      card.style.height = `${snappedHeight}px`;
      card.style.gridRowEnd = `span ${(snappedHeight + 12) / 2}`;
    };
    snapHeightToRules();
    const frame = window.requestAnimationFrame(snapHeightToRules);
    window.addEventListener("resize", snapHeightToRules);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", snapHeightToRules);
      card.style.height = "";
      card.style.gridRowEnd = "";
    };
  }, [character, detailed]);
  return (
    <article ref={cardRef} className={`speaker-card${detailed ? " is-detailed" : " is-script-cast"}${detailed && compactSettings.length === 0 ? " has-no-compact-settings" : ""}`}>
      <ScriptCastAvatar character={character} />
      <div className="speaker-card-content">
        <div className="speaker-card-primary">
          <strong>{character.name}</strong>
          <SpeakerCardActions character={character} onPlay={onPlay} playingReference={Boolean(playingReference)} onEdit={onEdit} onEditScriptContext={onEditScriptContext} onDelete={onDelete} />
        </div>
        {showRole && <p className="script-cast-role">{scriptContext?.role}</p>}
        {description && <p className="script-cast-context">{description}</p>}
        {detailed ? (
          <>
            {compactSettings.length > 0 && (
              <dl className={`speaker-card-settings is-compact compact-count-${Math.min(compactSettings.length, 3)}`}>
                {compactSettings.map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            )}
            {detailSettings.length > 0 && (
              <dl className="speaker-card-settings is-details">
                {detailSettings.map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            )}
          </>
        ) : null}
      </div>
    </article>
  );
}
