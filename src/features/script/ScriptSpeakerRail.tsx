import { useEffect, useMemo, useRef, useState } from "react";
import type { DialogueLine } from "../../types";
import { ResettableRangeInput } from "../shared/ResettableRangeInput";
import { selectedTake } from "../shared/studio-utils";
import { isMeanFlowSelection } from "../shared/ttsSampling";
import { ScriptCfgControls } from "./ScriptCfgControls";
import { SpeakerCard } from "./SpeakerCard";
import type { ScriptViewProps } from "./ScriptViewTypes";

function lineActiveCastIds(line: DialogueLine): string[] {
  const current = selectedTake(line);
  const active = current?.characterId || line.characterId;
  return active ? [active] : [];
}

function useEditableValue(editing: boolean, editor: React.RefObject<HTMLSpanElement | null>) {
  useEffect(() => {
    if (!editing || !editor.current) return;
    editor.current.focus();
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(editor.current);
    selection?.removeAllRanges();
    selection?.addRange(range);
  }, [editing, editor]);
}

function CastList({ project, characters, onPlayReference, playingReferenceCharacterId, onEdit, onSwitch }: Pick<ScriptViewProps, "project" | "onPlayReference" | "playingReferenceCharacterId"> & { characters: ScriptViewProps["project"]["characters"]; onEdit: (id: string) => void; onSwitch: () => void }) {
  return (
    <section className="cast-list-card">
      <h3>キャスト一覧</h3>
      <div className="cast-list">
        {characters.length ? (
          characters.map((character) => <SpeakerCard key={character.id} character={character} scriptContext={project.scriptCastContexts?.[character.id]} onEditScriptContext={() => onEdit(character.id)} onPlay={onPlayReference} playingReference={playingReferenceCharacterId === character.id} />)
        ) : (
          <div className="cast-list-empty">
            発話行にキャストを設定すると
            <br />
            ここに表示されます。
          </div>
        )}
      </div>
      <button className="rail-action-button" onClick={onSwitch}>
        キャストの一括切り替え
      </button>
    </section>
  );
}

function QualityPresetControls({ project, onSettings }: Pick<ScriptViewProps, "project" | "onSettings">) {
  return (
    <div className="preset-options">
      <button className={project.settings.quality === "turbo" ? "chosen" : ""} onClick={() => onSettings({ quality: "turbo", steps: 8 })}>
        高速 <small>Sway 8</small>
      </button>
      <button className={project.settings.quality === "fast" ? "chosen" : ""} onClick={() => onSettings({ quality: "fast", steps: 16 })}>
        バランス <small>Sway 16</small>
      </button>
      <button className={project.settings.quality === "quality" ? "chosen" : ""} onClick={() => onSettings({ quality: "quality", steps: 40 })}>
        高品質 <small>Linear 40</small>
      </button>
    </div>
  );
}

export function ScriptSpeakerRail({
  project,
  onPlayReference,
  playingReferenceCharacterId,
  onSettings,
  onEditScriptContext,
  onOpenCastSwitch,
}: Pick<ScriptViewProps, "project" | "onPlayReference" | "playingReferenceCharacterId" | "onSettings"> & { onEditScriptContext: (id: string) => void; onOpenCastSwitch: () => void }) {
  const [editingLineGap, setEditingLineGap] = useState(false);
  const [editingSpeechRate, setEditingSpeechRate] = useState(false);
  const lineGapEditor = useRef<HTMLSpanElement>(null);
  const speechRateEditor = useRef<HTMLSpanElement>(null);
  const speechRateEditCancelled = useRef(false);
  useEditableValue(editingLineGap, lineGapEditor);
  useEditableValue(editingSpeechRate, speechRateEditor);
  const lineGap = project.settings.lineGap ?? 0.7;
  const speechRate = project.settings.speechRate;
  const meanflow = isMeanFlowSelection(project.ttsSelection);
  const castCharacters = useMemo(() => {
    const activeIds = new Set<string>();
    for (const scene of project.scenes) for (const line of scene.lines) for (const characterId of lineActiveCastIds(line)) activeIds.add(characterId);
    return project.characters.filter((character) => activeIds.has(character.id));
  }, [project]);
  const commitLineGap = (raw: string) => {
    const value = Number(raw.replace(/秒/g, "").trim());
    if (Number.isFinite(value)) onSettings({ lineGap: Math.max(0, Math.min(9999, value)) });
    setEditingLineGap(false);
  };
  const commitSpeechRate = (raw: string) => {
    const value = Number(raw.replace(/倍/g, "").trim());
    if (Number.isFinite(value)) onSettings({ speechRate: Math.max(0.5, Math.min(2.0, value)) });
    setEditingSpeechRate(false);
  };
  return (
    <aside className="speaker-rail">
      <CastList project={project} characters={castCharacters} onPlayReference={onPlayReference} playingReferenceCharacterId={playingReferenceCharacterId} onEdit={onEditScriptContext} onSwitch={onOpenCastSwitch} />
      <div className="preset-card">
        <h3>{meanflow ? "音声設定" : "音声品質"}</h3>
        {!meanflow && <QualityPresetControls project={project} onSettings={onSettings} />}
        <label className="gap-control">
          <span>
            話速{" "}
            <b
              ref={speechRateEditor}
              className={`gap-value-label ${editingSpeechRate ? "is-editing" : ""}`}
              role="button"
              tabIndex={0}
              contentEditable={editingSpeechRate}
              suppressContentEditableWarning
              title="クリックして0.5〜2.0倍を直接入力"
              aria-label="共通の話速"
              onClick={() => {
                if (!editingSpeechRate) {
                  speechRateEditCancelled.current = false;
                  setEditingSpeechRate(true);
                }
              }}
              onBlur={(event) => {
                if (speechRateEditCancelled.current) {
                  speechRateEditCancelled.current = false;
                  setEditingSpeechRate(false);
                  return;
                }
                commitSpeechRate(event.currentTarget.textContent ?? "");
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  event.currentTarget.blur();
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  speechRateEditCancelled.current = true;
                  event.currentTarget.blur();
                }
              }}
            >
              {editingSpeechRate ? String(speechRate) : `${speechRate.toFixed(2)} 倍`}
            </b>
          </span>
          <ResettableRangeInput aria-label="共通の話速（スライダー）" className="range-control" min={0.5} max={2} step={0.01} value={speechRate} initialValue={1.2} onValueChange={(speechRate) => onSettings({ speechRate })} />
        </label>
        <label className="gap-control">
          <span>
            発話間隔{" "}
            <b
              ref={lineGapEditor}
              className={`gap-value-label ${editingLineGap ? "is-editing" : ""}`}
              role="button"
              tabIndex={0}
              contentEditable={editingLineGap}
              suppressContentEditableWarning
              title="クリックして9999秒まで直接入力"
              aria-label="共通の発話間隔（秒）"
              onClick={() => !editingLineGap && setEditingLineGap(true)}
              onBlur={(event) => commitLineGap(event.currentTarget.textContent ?? "")}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  event.currentTarget.blur();
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  setEditingLineGap(false);
                }
              }}
            >
              {editingLineGap ? String(lineGap) : `${lineGap.toFixed(1)} 秒`}
            </b>
          </span>
          <ResettableRangeInput className="range-control" min={0} max={5} step={0.1} value={Math.min(5, lineGap)} initialValue={0.7} onValueChange={(lineGap) => onSettings({ lineGap })} />
        </label>
        {!meanflow && <ScriptCfgControls settings={project.settings} onSettings={onSettings} />}
      </div>
    </aside>
  );
}
