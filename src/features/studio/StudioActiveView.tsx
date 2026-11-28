import { lazy, Suspense } from "react";
import { PronunciationTab } from "../pronunciation/PronunciationTab";
import { cueLineIds } from "../script/dialogueCues";
import { modifiedLinePointerSelection } from "../script/linePointerSelection";
import { StudioSecondaryTabs } from "./StudioSecondaryTabs";
import { loadCharactersView } from "./secondaryTabLoaders";
import { projectCharacterOrder } from "../shared/projectCharacterOrder";
import type { StudioController } from "./useStudioController";

const CharactersView = lazy(loadCharactersView);
const ScriptView = lazy(() => import("../script/ScriptView").then((module) => ({ default: module.ScriptView })));

function followedLine(model: StudioController) {
  const playback = (model.autoScrollEnabled && model.autoScrollTarget === "playback") || model.playbackHoverFollow;
  const exporting = (model.autoScrollEnabled && model.autoScrollTarget === "export") || model.exportHoverFollow;
  const lineId = playback ? model.playingLineId : exporting ? model.generatingLineId : null;
  return lineId?.split("|")[0] ?? null;
}

function focusLine(model: StudioController, lineId: string, modifiers: { shiftKey: boolean; altKey: boolean; preserveSelection?: boolean }) {
  const { project, focusedLineId, selectedLineIds, selectionAnchorLineId } = model;
  if (!project) return;
  if (modifiers.preserveSelection && selectedLineIds.includes(lineId)) return void model.setFocusedLineId(lineId);
  const modified = modifiedLinePointerSelection({ project, clickedLineId: lineId, focusedLineId, selectedLineIds, anchorLineId: selectionAnchorLineId, modifiers });
  if (modified) {
    model.setFocusedLineId(modified.focusedLineId);
    model.setSelectedLineIds(modified.selectedLineIds);
    model.setSelectionAnchorLineId(modified.anchorLineId);
    return;
  }
  const cueIds = cueLineIds(project, lineId);
  model.setFocusedLineId(lineId);
  model.setSelectedLineIds(selectedLineIds.includes(lineId) && selectedLineIds.length > 1 ? [lineId] : cueIds);
  model.setSelectionAnchorLineId(lineId);
}

function ScriptActiveView({ model }: { model: StudioController }) {
  const p = model.project!;
  return (
    <ScriptView
      project={p}
      busy={model.autoRenderInProgress.current ? null : model.busy}
      generatingLineId={model.generatingLineId}
      onCommitLineContent={model.commitLineContent}
      onQueueAutoRender={model.queueAutoRender}
      onTextFocus={model.rememberTextFocus}
      onNotice={model.setNotice}
      onUpdateScene={model.updateScene}
      onUpdateLine={model.updateLine}
      onAdjustLineGaps={model.adjustLineGaps}
      onSetLineGaps={model.setLineGaps}
      onAdjustLineNumericField={model.adjustLineNumericField}
      onSetLineNumericField={model.setLineNumericField}
      onSetLineSeeds={model.setLineSeeds}
      onReplaceLineTexts={model.replaceLineTexts}
      onChangeLineCharacter={model.changeLineCharacter}
      onSwitchCharacters={model.switchCharacters}
      onAddLine={model.addLine}
      onSplitLine={model.splitLine}
      onAddCueMember={model.addCueMember}
      onOpenLineAssistant={model.openLineAssistant}
      onOpenRewriteAssistant={(lineIds, sourceLineId) => {
        const current = model.selectedLineIdsRef.current;
        model.setLineAssistantTarget({ kind: "rewrite", lineIds: [...(current.length > 1 && current.includes(sourceLineId) ? current : lineIds)] });
      }}
      onAddScene={model.addScene}
      onGenerate={(_sceneId, line) => model.generateSelectedLines(false, line.id)}
      onGenerateWithSeed={model.generateTakeWithSeed}
      onRegenerate={(_sceneId, line) => model.generateSelectedLines(true, line.id)}
      onDeleteTake={model.deleteTake}
      onDeleteLine={(sceneId, line) => (model.selectedLineIdsRef.current.length > 1 && model.selectedLineIdsRef.current.includes(line.id) ? model.deleteSelectedLines() : model.deleteLine(sceneId, line))}
      onDeleteContextLines={model.deleteContextLines}
      onCleanupLineTakes={model.cleanupSelectedTakes}
      onDeleteScene={model.deleteScene}
      onPlay={(url, lineId) => (lineId ? void model.playSelected(lineId) : model.play(url))}
      onPlayReference={model.playReference}
      playingReferenceCharacterId={model.playingReferenceCharacterId}
      onUpdateTitle={(title) => model.updateProject((current) => ({ ...current, title }), "台本タイトルを保存しました")}
      onSettings={(patch) => model.updateProject((current) => ({ ...current, settings: { ...current.settings, ...patch } }), "生成設定を保存しました")}
      onSelectTake={(sceneId, lineId, takeId) => {
        const selected = p.scenes
          .flatMap((scene) => scene.lines)
          .find((line) => line.id === lineId)
          ?.takes.find((take) => take.id === takeId);
        model.updateLine(sceneId, lineId, { selectedTakeId: takeId, ...(selected?.characterId ? { characterId: selected.characterId } : {}) });
      }}
      onUpdateCastContext={(characterId, context) => model.updateProject((current) => ({ ...current, scriptCastContexts: { ...current.scriptCastContexts, [characterId]: context } }), "台本上のキャスト設定を保存しました")}
      onMoveLines={model.moveLines}
      onSelectDraggedLines={(lineIds, lineId) => {
        model.setFocusedLineId(lineId);
        model.setSelectedLineIds(lineIds);
        model.setSelectionAnchorLineId(lineId);
      }}
      focusedLineId={model.focusedLineId}
      selectedLineIds={model.selectedLineIds}
      playingLineId={model.playingLineId}
      followedLineId={followedLine(model)}
      continuousPlayback={model.continuousPlayback}
      onFocusLine={(lineId, modifiers = { shiftKey: false, altKey: false }) => focusLine(model, lineId, modifiers)}
    />
  );
}

function CharactersActiveView({ model }: { model: StudioController }) {
  const p = model.project!;
  return (
    <CharactersView
      active
      project={p}
      connection={model.connection}
      notice={model.notice}
      busy={model.busy}
      onAccept={model.acceptCandidate}
      onImport={model.importReference}
      onUpdate={model.updateCharacter}
      onUpdateReference={model.updateCharacterReference}
      onApplyCandidateReference={model.applyCandidateReference}
      onUpdateAvatar={model.updateCharacterAvatar}
      onRemoveAvatar={model.removeCharacterAvatar}
      onDelete={model.deleteCharacter}
      onReorder={model.reorderCharacters}
      onGenerateCandidates={model.generateCandidates}
      onImportVoiceDesignReference={model.importVoiceDesignReference}
      onSaveVoiceDesign={model.saveVoiceDesign}
      onClearCandidates={model.clearCandidates}
      onClearCandidateScope={model.clearCandidateScope}
      onNotice={model.setNotice}
      onStatusNotice={model.setStatusNotice}
      onBusy={model.setBusy}
      onImportCasts={() => void model.prepareCastImport()}
    />
  );
}

export function StudioActiveView({ model }: { model: StudioController }) {
  if (!model.project) return null;
  return (
    <>
      <Suspense fallback={<div className="boot-card">読み込んでいます…</div>}>
        {model.tab === "script" && <ScriptActiveView model={model} />}
        {model.tab === "characters" && <CharactersActiveView model={model} />}
        {model.tab === "pronunciation" && <PronunciationTab active characters={projectCharacterOrder(model.project)} onNotice={model.setNotice} onRegenerate={model.regenerateDictionaryLines} />}
      </Suspense>
      <StudioSecondaryTabs model={model} />
    </>
  );
}
