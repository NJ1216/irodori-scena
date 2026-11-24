/* eslint-disable react-hooks/set-state-in-effect -- This component synchronizes controlled drafts, imperative media, or stable lifecycle owners at explicit boundaries. */
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { Character, DialogueLine, Scene, Take } from "../../types";
import { LINE_INSERT_REVEAL_DELAY_MS } from "../shared/studio-utils";
import { prepareScriptSceneSnapshot } from "./scriptSceneCapture";

import { LineEditor } from "./LineEditor";
import { VirtualSceneCues } from "./VirtualSceneCues";
import type { LineTextEditorElement } from "./EmojiTextArea";
import { cueMetadataByLine, sceneDialogueCues } from "./dialogueCues";
import type { LineSelectionModifiers } from "./linePointerSelection";
import type { BatchLineNumericField } from "./lineNumericBatch";
import type { LineSeedPatch } from "./lineSeedBatch";

const DELETE_CONFIRMATION_TIMEOUT_MS = 4_000;

export function SceneTitleInput({ sceneId, title, onCommit }: { sceneId: string; title: string; onCommit: (sceneId: string, patch: Partial<Scene>) => void }) {
  const [draft, setDraft] = useState(title);
  const cancelled = useRef(false);
  useEffect(() => setDraft(title), [title]);
  const commit = () => {
    if (cancelled.current) {
      cancelled.current = false;
      setDraft(title);
      return;
    }
    if (draft !== title) onCommit(sceneId, { title: draft });
  };
  return (
    <input
      value={draft}
      aria-label="シーンタイトル"
      onChange={(event) => setDraft(event.currentTarget.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") event.currentTarget.blur();
        if (event.key === "Escape") {
          cancelled.current = true;
          setDraft(title);
          event.currentTarget.blur();
        }
      }}
    />
  );
}

function isLinePlaying(lineId: string, cueLines: DialogueLine[] | undefined, playingLineId: string | null, continuousPlayback: boolean) {
  if (!playingLineId) return false;
  const activeIds = playingLineId.split("|");
  if (activeIds.includes(lineId)) return true;
  return !continuousPlayback && Boolean(cueLines?.some((line) => activeIds.includes(line.id)));
}

function cueGapBinding(cueLines: DialogueLine[] | undefined, fallback: DialogueLine) {
  const gapLine = cueLines?.[0] || fallback;
  return { gapLine, gapLineId: gapLine.id };
}

function rewriteActionState(line: DialogueLine, cueLines: DialogueLine[], grouped: boolean, selectedLineIds: string[]) {
  const selected = selectedLineIds.includes(line.id);
  if (selectedLineIds.length > 1) {
    return { selected, targetLineIds: selected ? selectedLineIds : [], persistent: selected };
  }
  return { selected, targetLineIds: grouped ? cueLines.map((member) => member.id) : [line.id], persistent: false };
}

function selectedNumericFieldAdjustment(lineId: string, selectedLineIds: string[], onAdjust: (lineIds: string[], field: BatchLineNumericField, directions: readonly (-1 | 1)[]) => void) {
  if (selectedLineIds.length <= 1 || !selectedLineIds.includes(lineId)) return undefined;
  return (field: BatchLineNumericField, directions: readonly (-1 | 1)[]) => onAdjust(selectedLineIds, field, directions);
}

function selectedNumericFieldSetting(lineId: string, selectedLineIds: string[], onSet: (lineIds: string[], field: BatchLineNumericField, value: number | undefined) => void) {
  if (selectedLineIds.length <= 1 || !selectedLineIds.includes(lineId)) return undefined;
  return (field: BatchLineNumericField, value: number | undefined) => onSet(selectedLineIds, field, value);
}

function selectedGapAction(lineIds: string[], selectedLineIds: string[]) {
  return selectedLineIds.length > 1 && lineIds.some((lineId) => selectedLineIds.includes(lineId));
}

function selectedGapHandlers(selected: boolean, lineId: string, selectedLineIds: string[], onAdjust: (lineIds: string[], directions: readonly (-1 | 1)[]) => void, onSet: (lineIds: string[], value: number | undefined) => void, onPreview: (sourceLineId: string, directions: readonly (-1 | 1)[] | null) => void) {
  if (!selected) return {};
  return {
    onAdjustSelectedGaps: (directions: readonly (-1 | 1)[]) => onAdjust(selectedLineIds, directions),
    onSetSelectedGaps: (value: number | undefined) => onSet(selectedLineIds, value),
    onPreviewSelectedGaps: (directions: readonly (-1 | 1)[] | null) => onPreview(lineId, directions),
  };
}

function selectedNumericFieldPreview(lineId: string, selectedLineIds: string[], onPreview: (sourceLineId: string, field: BatchLineNumericField, directions: readonly (-1 | 1)[] | null) => void) {
  if (selectedLineIds.length <= 1 || !selectedLineIds.includes(lineId)) return undefined;
  return (field: BatchLineNumericField, directions: readonly (-1 | 1)[] | null) => onPreview(lineId, field, directions);
}

function selectedSeedSetting(lineId: string, selectedLineIds: string[], onSet: (lineIds: string[], patch: LineSeedPatch) => void) {
  if (selectedLineIds.length <= 1 || !selectedLineIds.includes(lineId)) return undefined;
  return (patch: LineSeedPatch) => onSet(selectedLineIds, patch);
}

function useSceneLineLayout(scene: Scene) {
  return useMemo(() => {
    const cues = sceneDialogueCues(scene);
    return { cues, cueMetadata: cueMetadataByLine(cues), lineIndices: new Map(scene.lines.map((line, index) => [line.id, index])) };
  }, [scene]);
}

// eslint-disable-next-line max-lines-per-function
export function SceneEditor({
  scene,
  sceneLabel,
  totalLineCount,
  isLastScene,
  lineNumbers,
  lineReferences,
  characters,
  defaultGap,
  effectiveGapByLine,
  defaultSpeechRate,
  cfgDefaults,
  supportsRuntimeCfg,
  busy,
  generatingLineId,
  captionSupported,
  onCommitLineContent,
  onTextFocus,
  onUpdateScene,
  onUpdateLine,
  onAdjustLineGaps,
  onSetLineGaps,
  onAdjustLineNumericField,
  onSetLineNumericField,
  previewLines,
  onPreviewNumericField,
  onPreviewGaps,
  onSetLineSeeds,
  onChangeLineCharacter,
  onAddLine,
  onAddCueMember,
  onOpenLineAssistant,
  onOpenRewriteAssistant,
  onGenerate,
  onGenerateWithSeed,
  onRegenerate,
  onDeleteTake,
  onDeleteLine,
  onDeleteScene,
  onPlay,
  onSelectTake,
  focusedLineId,
  selectedLineIds,
  playingLineId,
  followedLineId,
  continuousPlayback,
  onFocusLine,
  onNotice,
}: {
  scene: Scene;
  sceneLabel: string;
  totalLineCount: number;
  isLastScene: boolean;
  lineNumbers: ReadonlyMap<string, number | null>;
  lineReferences: ReadonlyMap<string, number>;
  characters: Character[];
  defaultGap: number;
  effectiveGapByLine?: ReadonlyMap<string, number>;
  defaultSpeechRate: number;
  cfgDefaults: { textCfg: number; voiceCfg: number; captionCfg?: number };
  supportsRuntimeCfg: boolean;
  busy: string | null;
  generatingLineId: string | null;
  captionSupported: boolean;
  onCommitLineContent: (lineId: string, autoRender: boolean) => void;
  onTextFocus: (sceneId: string, lineId: string, element: LineTextEditorElement) => void;
  onUpdateScene: (sceneId: string, patch: Partial<Scene>) => void;
  onUpdateLine: (sceneId: string, lineId: string, patch: Partial<DialogueLine>) => void;
  onAdjustLineGaps: (lineIds: string[], directions: readonly (-1 | 1)[]) => void;
  onSetLineGaps: (lineIds: string[], value: number | undefined) => void;
  onAdjustLineNumericField: (lineIds: string[], field: BatchLineNumericField, directions: readonly (-1 | 1)[]) => void;
  onSetLineNumericField: (lineIds: string[], field: BatchLineNumericField, value: number | undefined) => void;
  previewLines?: ReadonlyMap<string, DialogueLine>;
  onPreviewNumericField: (sourceLineId: string, field: BatchLineNumericField, directions: readonly (-1 | 1)[] | null) => void;
  onPreviewGaps: (sourceLineId: string, directions: readonly (-1 | 1)[] | null) => void;
  onSetLineSeeds: (lineIds: string[], patch: LineSeedPatch) => void;
  onChangeLineCharacter: (line: DialogueLine, characterId: string) => Promise<void>;
  onAddLine: (sceneId: string, beforeLineId?: string) => Promise<void>;
  onAddCueMember: (sceneId: string, line: DialogueLine, characterId: string) => Promise<void>;
  onOpenLineAssistant: (sceneId: string, beforeLineId?: string) => void;
  onOpenRewriteAssistant: (lineIds: string[], sourceLineId: string) => void;
  onGenerate: (sceneId: string, line: DialogueLine) => Promise<unknown>;
  onGenerateWithSeed: (sceneId: string, line: DialogueLine, seed: number) => Promise<boolean>;
  onRegenerate: (sceneId: string, line: DialogueLine) => Promise<unknown>;
  onDeleteTake: (line: DialogueLine, take: Take) => Promise<void>;
  onDeleteLine: (sceneId: string, line: DialogueLine) => Promise<void>;
  onDeleteScene: (scene: Scene) => Promise<void>;
  onPlay: (url: string, lineId?: string) => void;
  onSelectTake: (sceneId: string, lineId: string, takeId: string) => void;
  focusedLineId: string | null;
  selectedLineIds: string[];
  playingLineId: string | null;
  followedLineId: string | null;
  continuousPlayback: boolean;
  onFocusLine: (lineId: string, modifiers?: LineSelectionModifiers) => void;
  onNotice: (message: string) => void;
}) {
  const { cues, cueMetadata, lineIndices } = useSceneLineLayout(scene);
  const focusedCueIndex = focusedLineId ? cueMetadata.get(focusedLineId)?.timelineIndex : undefined;
  const followedCueIndex = followedLineId ? cueMetadata.get(followedLineId)?.timelineIndex : undefined;
  const virtualized = totalLineCount > 200;
  const renderLine = (line: DialogueLine) => {
    const index = lineIndices.get(line.id)!;
    const metadata = cueMetadata.get(line.id)!;
    const { cue, memberIndex: cueIndex } = metadata;
    const cueHead = cueIndex === 0;
    const cueTail = cueIndex === cue.lines.length - 1;
    const grouped = cue.grouped && cue.lines.length > 1;
    const availableCharacters = characters.filter((character) => !cue.lines.some((member) => member.characterId === character.id));
    const gapBinding = cueGapBinding(cue.lines, line);
    const requestedGap = gapBinding.gapLine.gapSeconds ?? defaultGap;
    const effectiveGap = effectiveGapByLine?.get(cue.lines[0].id);
    const rewriteAction = rewriteActionState(line, cue.lines, grouped, selectedLineIds);
    const selectedGap = selectedGapAction(
      cue.lines.map((member) => member.id),
      selectedLineIds,
    );
    return (
      <Fragment key={line.id}>
        <LineEditor
          line={line}
          previewLine={previewLines?.get(line.id)}
          lineNumber={lineNumbers.get(line.id) ?? null}
          referenceNumber={lineReferences.get(line.id) ?? 1}
          characters={characters}
          defaultGap={defaultGap}
          defaultSpeechRate={defaultSpeechRate}
          cfgDefaults={cfgDefaults}
          supportsRuntimeCfg={supportsRuntimeCfg}
          focused={focusedLineId === line.id}
          selected={rewriteAction.selected}
          playing={isLinePlaying(line.id, cue.lines, playingLineId, continuousPlayback)}
          generating={generatingLineId === line.id}
          captionSupported={captionSupported}
          busy={busy === line.id}
          onFocusLine={(modifiers) => onFocusLine(line.id, modifiers)}
          onNotice={onNotice}
          onUpdate={(patch) => onUpdateLine(scene.id, line.id, patch)}
          onUpdateSeed={selectedSeedSetting(line.id, selectedLineIds, onSetLineSeeds)}
          gapLine={gapBinding.gapLine}
          previewGapLine={previewLines?.get(gapBinding.gapLineId)}
          onUpdateGap={(patch) => onUpdateLine(scene.id, gapBinding.gapLineId, patch)}
          {...selectedGapHandlers(selectedGap, line.id, selectedLineIds, onAdjustLineGaps, onSetLineGaps, onPreviewGaps)}
          onAdjustSelectedNumericField={selectedNumericFieldAdjustment(line.id, selectedLineIds, onAdjustLineNumericField)}
          onSetSelectedNumericField={selectedNumericFieldSetting(line.id, selectedLineIds, onSetLineNumericField)}
          onPreviewSelectedNumericField={selectedNumericFieldPreview(line.id, selectedLineIds, onPreviewNumericField)}
          effectiveGapSeconds={effectiveGap !== undefined && effectiveGap > requestedGap ? effectiveGap : undefined}
          onCommitContent={(autoRender) => onCommitLineContent(line.id, autoRender)}
          onTextFocus={(element) => onTextFocus(scene.id, line.id, element)}
          onChangeCharacter={(characterId) => onChangeLineCharacter(line, characterId)}
          onGenerate={() => onGenerate(scene.id, line)}
          onGenerateWithSeed={(seed) => onGenerateWithSeed(scene.id, line, seed)}
          onRegenerate={() => onRegenerate(scene.id, line)}
          onDeleteTake={(take) => onDeleteTake(line, take)}
          onDelete={() => onDeleteLine(scene.id, line)}
          onPlay={onPlay}
          onSelectTake={(takeId) => onSelectTake(scene.id, line.id, takeId)}
          grouped={grouped}
          cueHead={cueHead}
          cueTail={cueTail}
          isLastLine={isLastScene && index === scene.lines.length - 1}
          availableCueCharacters={availableCharacters}
          onAddCueMember={(characterId) => onAddCueMember(scene.id, line, characterId)}
          rewriteTargetLineIds={rewriteAction.targetLineIds}
          rewriteActionPersistent={rewriteAction.persistent}
          onOpenRewriteAssistant={onOpenRewriteAssistant}
        />
        {(!grouped || cueTail) && (
          <LineInsertControl
            label={index === scene.lines.length - 1 ? "＋ 発話行を追加" : "発話行を挿入"}
            append={index === scene.lines.length - 1}
            beforeLineId={scene.lines[index + 1]?.id}
            onInsert={() => onAddLine(scene.id, index === scene.lines.length - 1 ? undefined : scene.lines[index + 1]?.id)}
            onAssist={() => onOpenLineAssistant(scene.id, index === scene.lines.length - 1 ? undefined : scene.lines[index + 1]?.id)}
          />
        )}
      </Fragment>
    );
  };
  return (
    <article className="scene-box" data-scene-id={scene.id}>
      <SceneHeader scene={scene} sceneLabel={sceneLabel} busy={busy === scene.id} onUpdate={onUpdateScene} onDelete={onDeleteScene} />
      <div className="line-stack" data-virtualized={virtualized || undefined}>
        <LineInsertControl label={scene.lines.length ? "発話行を挿入" : "＋ 発話行を追加"} append={!scene.lines.length} beforeLineId={scene.lines[0]?.id} onInsert={() => onAddLine(scene.id, scene.lines[0]?.id)} onAssist={() => onOpenLineAssistant(scene.id, scene.lines[0]?.id)} />
        {virtualized ? <VirtualSceneCues cues={cues} focusedCueIndex={focusedCueIndex} followedCueIndex={followedCueIndex} renderCue={(cue) => cue.lines.map(renderLine)} /> : scene.lines.map(renderLine)}
      </div>
    </article>
  );
}

function SceneHeader({ scene, sceneLabel, busy, onUpdate, onDelete }: { scene: Scene; sceneLabel: string; busy: boolean; onUpdate: (sceneId: string, patch: Partial<Scene>) => void; onDelete: (scene: Scene) => Promise<void> }) {
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const deleteConfirmTimer = useRef<number | null>(null);
  const deleteLabel = confirmingDelete ? "もう一度押してシーンを削除" : "シーン全体を削除";

  const cancelDeleteConfirmation = () => {
    if (deleteConfirmTimer.current !== null) {
      window.clearTimeout(deleteConfirmTimer.current);
      deleteConfirmTimer.current = null;
    }
    if (!busy) setConfirmingDelete(false);
  };

  useEffect(
    () => () => {
      if (deleteConfirmTimer.current !== null) {
        window.clearTimeout(deleteConfirmTimer.current);
      }
    },
    [],
  );

  return (
    <div
      className="scene-header"
      onMouseLeave={cancelDeleteConfirmation}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          cancelDeleteConfirmation();
        }
      }}
    >
      <span className="scene-number">
        <span className={`circle-number-glyph${/^\d{3}$/.test(sceneLabel) ? " is-three-digits" : ""}`}>{sceneLabel}</span>
      </span>
      <SceneTitleInput sceneId={scene.id} title={scene.title} onCommit={onUpdate} />
      <button
        type="button"
        className={`delete-scene ${confirmingDelete ? "is-confirming" : ""}`}
        title={deleteLabel}
        aria-label={deleteLabel}
        disabled={busy}
        onClick={() => {
          if (confirmingDelete) {
            cancelDeleteConfirmation();
            void onDelete(scene);
            return;
          }
          setConfirmingDelete(true);
          prepareScriptSceneSnapshot(scene.id);
          deleteConfirmTimer.current = window.setTimeout(cancelDeleteConfirmation, DELETE_CONFIRMATION_TIMEOUT_MS);
        }}
      >
        <svg className="trash-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4 7h16M10 11v6m4-6v6M9 7l1-2h4l1 2m-9 0 1 13h10l1-13" />
        </svg>
        {confirmingDelete ? "もう一度押して削除" : "シーンを削除"}
      </button>
    </div>
  );
}

function LineInsertControl({ label, append = false, beforeLineId, onInsert, onAssist }: { label: string; append?: boolean; beforeLineId?: string; onInsert: () => Promise<void>; onAssist: () => void }) {
  const [revealed, setRevealed] = useState(false);
  const [hovered, setHovered] = useState(false);
  const timer = useRef<number | null>(null);
  const clearTimer = () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  };
  return (
    <div
      className={`insert-zone line-insert-zone ${append ? "is-append" : ""} ${revealed ? "is-revealed" : ""}`}
      data-line-drop-before={beforeLineId ?? ""}
      onMouseEnter={() => {
        clearTimer();
        setHovered(true);
        timer.current = window.setTimeout(() => setRevealed(true), LINE_INSERT_REVEAL_DELAY_MS);
      }}
      onMouseLeave={() => {
        clearTimer();
        setHovered(false);
        setRevealed(false);
      }}
    >
      {(append || hovered) && !revealed && (
        <button type="button" className="insert-marker" aria-label="発話行を追加" onClick={() => void onInsert()}>
          ＋
        </button>
      )}
      <div className="insert-actions line-insert-actions">
        <button className="insert-action" onClick={() => void onInsert()}>
          {label}
        </button>
        <button className="insert-action insert-action-ai" onClick={onAssist}>
          ✦ AIに依頼
        </button>
      </div>
    </div>
  );
}

export function SceneInsertControl({ label, onInsert, empty = false }: { label: string; onInsert: () => void; empty?: boolean }) {
  const [revealed, setRevealed] = useState(false);
  const [hovered, setHovered] = useState(false);
  const timer = useRef<number | null>(null);
  const clearTimer = () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  };
  return (
    <div
      className={`insert-zone scene-insert-zone ${empty ? "empty-scene-zone" : ""} ${revealed ? "is-revealed" : ""}`}
      onMouseEnter={() => {
        clearTimer();
        setHovered(true);
        if (empty) {
          setRevealed(true);
          return;
        }
        timer.current = window.setTimeout(() => setRevealed(true), LINE_INSERT_REVEAL_DELAY_MS);
      }}
      onMouseLeave={() => {
        clearTimer();
        setHovered(false);
        setRevealed(false);
      }}
    >
      {!empty && hovered && !revealed && (
        <button type="button" className="insert-marker" aria-label="シーンを追加" onClick={onInsert}>
          ＋
        </button>
      )}
      <div className="insert-actions scene-insert-actions">
        <button className="insert-action" onClick={onInsert}>
          {label}
        </button>
      </div>
    </div>
  );
}
