import { Fragment, useLayoutEffect, useMemo, useState, useSyncExternalStore, type KeyboardEventHandler, type MouseEvent, type Ref } from "react";
import type { DialogueLine } from "../../types";
import { projectPlaybackDurationSeconds, sceneLabel } from "../shared/studio-utils";
import { projectEffectiveGaps } from "./dialogueCues";
import { ProjectTitleEditor } from "./ProjectTitleEditor";
import { SceneEditor, SceneInsertControl } from "./SceneEditor";
import { ScriptSearchBar } from "./ScriptSearchBar";
import type { ScriptViewProps } from "./ScriptViewTypes";
import { scriptLineMaps } from "./scriptLineNumbers";
import type { useLineReorderDrag } from "./useLineReorderDrag";
import { isMeanFlowSelection } from "../shared/ttsSampling";
import { adjustSelectedLineGaps } from "./lineGapBatch";
import { adjustSelectedLineNumericField, type BatchLineNumericField } from "./lineNumericBatch";
import { cancelRestoredScriptLineEffects, cancelScriptLineDeletionEffects, finishScriptLineCompaction, hiddenScriptLineIds, subscribeScriptLineDeletion } from "./scriptLineDeletionMotion";
import { cancelRestoredScriptSceneEffects, cancelScriptSceneDeletionEffects, finishScriptSceneCompaction, hiddenScriptSceneIds, subscribeScriptSceneDeletion } from "./scriptSceneDeletionMotion";
import { cancelScriptLineRestoration, finishScriptLineRestoration } from "./scriptLineRestorationMotion";
import { LineContextMenu, type LineMenuState } from "./LineContextMenu";

type DragHandlers = ReturnType<typeof useLineReorderDrag>["handlers"];
type NumericPreview = { sourceLineId: string; selectedLineIds: string[]; field: BatchLineNumericField | "gap"; directions: readonly (-1 | 1)[] };

function openLineContextMenu(event: MouseEvent<HTMLElement>, props: ScriptViewProps, setMenu: (value: LineMenuState) => void) {
  const target = event.target as HTMLElement;
  if (target.closest("input, textarea, [contenteditable='true']")) return;
  const id = target.closest<HTMLElement>("article[data-line-id]")?.dataset.lineId;
  if (!id) return;
  event.preventDefault();
  const ids = props.selectedLineIds.includes(id) ? props.selectedLineIds : [id];
  if (!props.selectedLineIds.includes(id)) props.onSelectDraggedLines([id], id);
  setMenu({ sourceId: id, ids, x: event.clientX, y: event.clientY });
}

export function ScriptCanvas({ view: props, rootRef, dragHandlers, onKeyDown }: { view: ScriptViewProps; rootRef: Ref<HTMLElement>; dragHandlers: DragHandlers; onKeyDown: KeyboardEventHandler<HTMLElement> }) {
  const { onFocusLine, onReplaceLineTexts, onUpdateTitle, onAddScene } = props;
  const { focusedLineId, project: sourceProject } = props;
  const hiddenIds = useSyncExternalStore(subscribeScriptLineDeletion, hiddenScriptLineIds);
  const hiddenScenes = useSyncExternalStore(subscribeScriptSceneDeletion, hiddenScriptSceneIds);
  const project = useMemo(
    () => (hiddenIds.size || hiddenScenes.size ? { ...props.project, scenes: props.project.scenes.filter((scene) => !hiddenScenes.has(scene.id)).map((scene) => (hiddenIds.size ? { ...scene, lines: scene.lines.filter((line) => !hiddenIds.has(line.id)) } : scene)) } : props.project),
    [props.project, hiddenIds, hiddenScenes],
  );
  useLayoutEffect(() => {
    finishScriptLineCompaction();
  }, [project]);
  useLayoutEffect(() => {
    finishScriptSceneCompaction();
  }, [project]);
  useLayoutEffect(() => {
    cancelRestoredScriptLineEffects(props.project);
  }, [props.project]);
  useLayoutEffect(() => {
    const missing = finishScriptLineRestoration(sourceProject);
    if (missing && focusedLineId !== missing) onFocusLine(missing);
  }, [sourceProject, focusedLineId, onFocusLine]);
  useLayoutEffect(() => {
    cancelRestoredScriptSceneEffects(props.project);
  }, [props.project]);
  useLayoutEffect(() => () => cancelScriptLineDeletionEffects(), [props.project.id]);
  useLayoutEffect(() => () => cancelScriptLineRestoration(), [props.project.id]);
  useLayoutEffect(() => () => cancelScriptSceneDeletionEffects(), [props.project.id]);
  const [preview, setPreview] = useState<NumericPreview | null>(null);
  const [menu, setMenu] = useState<LineMenuState | null>(null);
  const activePreview = preview && preview.selectedLineIds.length === props.selectedLineIds.length && preview.selectedLineIds.every((id) => props.selectedLineIds.includes(id)) ? preview : null;
  const previewLines = useMemo(() => {
    if (!activePreview) return undefined;
    const adjusted = activePreview.field === "gap" ? adjustSelectedLineGaps(project, activePreview.selectedLineIds, activePreview.directions) : adjustSelectedLineNumericField(project, activePreview.selectedLineIds, activePreview.field, activePreview.directions);
    return new Map<string, DialogueLine>(adjusted.scenes.flatMap((scene) => scene.lines.map((line) => [line.id, line] as const)));
  }, [project, activePreview]);
  const updatePreview = (sourceLineId: string, field: BatchLineNumericField | "gap", directions: readonly (-1 | 1)[] | null) => {
    setPreview(directions ? { sourceLineId, selectedLineIds: [...props.selectedLineIds], field, directions } : null);
  };
  const effectiveGapByLine = useMemo(() => projectEffectiveGaps(project), [project]);
  const totalLineCount = useMemo(() => project.scenes.reduce((count, scene) => count + scene.lines.length, 0), [project.scenes]);
  const supportsRuntimeCfg = !isMeanFlowSelection(project.ttsSelection);
  const { numbers: lineNumbers, references: lineReferences } = useMemo(() => scriptLineMaps(project), [project]);
  return (
    <section ref={rootRef} className="script-canvas" onKeyDown={onKeyDown} onContextMenu={(event) => openLineContextMenu(event, props, setMenu)} {...dragHandlers}>
      <ScriptSearchBar project={project} onFocusLine={onFocusLine} onReplace={onReplaceLineTexts} />
      <ProjectTitleEditor title={project.title} durationSeconds={projectPlaybackDurationSeconds(project)} onCommit={onUpdateTitle} />
      <div className={`scene-stack ${project.scenes.length ? "" : "is-empty"}`}>
        {project.scenes.length === 0 ? (
          <SceneInsertControl empty label="＋ シーンと発話行を追加" onInsert={() => onAddScene(undefined, true)} />
        ) : (
          <>
            <SceneInsertControl label="＋ シーンを挿入" onInsert={() => onAddScene(project.scenes[0]?.id)} />
            {project.scenes.map((scene, index) => (
              <Fragment key={scene.id}>
                <SceneEditor
                  scene={scene}
                  sceneLabel={sceneLabel(index)}
                  totalLineCount={totalLineCount}
                  isLastScene={index === project.scenes.length - 1}
                  lineNumbers={lineNumbers}
                  lineReferences={lineReferences}
                  characters={project.characters}
                  defaultGap={project.settings.lineGap ?? 0.7}
                  effectiveGapByLine={effectiveGapByLine}
                  defaultSpeechRate={project.settings.speechRate}
                  cfgDefaults={project.settings}
                  supportsRuntimeCfg={supportsRuntimeCfg}
                  busy={props.busy}
                  generatingLineId={props.generatingLineId}
                  captionSupported={!project.ttsSelection?.model?.repo.endsWith("-v3") && !project.ttsSelection?.model?.repo.endsWith("-v2")}
                  onCommitLineContent={props.onCommitLineContent}
                  onTextFocus={props.onTextFocus}
                  onUpdateScene={props.onUpdateScene}
                  onUpdateLine={props.onUpdateLine}
                  onAdjustLineGaps={props.onAdjustLineGaps}
                  onSetLineGaps={props.onSetLineGaps}
                  onAdjustLineNumericField={props.onAdjustLineNumericField}
                  onSetLineNumericField={props.onSetLineNumericField}
                  previewLines={previewLines}
                  onPreviewNumericField={updatePreview}
                  onPreviewGaps={(sourceLineId, directions) => updatePreview(sourceLineId, "gap", directions)}
                  onSetLineSeeds={props.onSetLineSeeds}
                  onChangeLineCharacter={props.onChangeLineCharacter}
                  onAddLine={props.onAddLine}
                  onAddCueMember={props.onAddCueMember}
                  onOpenLineAssistant={props.onOpenLineAssistant}
                  onOpenRewriteAssistant={props.onOpenRewriteAssistant}
                  onGenerate={props.onGenerate}
                  onGenerateWithSeed={props.onGenerateWithSeed}
                  onRegenerate={props.onRegenerate}
                  onDeleteTake={props.onDeleteTake}
                  onDeleteLine={props.onDeleteLine}
                  onDeleteScene={props.onDeleteScene}
                  onPlay={props.onPlay}
                  onSelectTake={props.onSelectTake}
                  focusedLineId={props.focusedLineId}
                  selectedLineIds={props.selectedLineIds}
                  playingLineId={props.playingLineId}
                  followedLineId={props.followedLineId}
                  continuousPlayback={props.continuousPlayback}
                  onFocusLine={props.onFocusLine}
                  onNotice={props.onNotice}
                />
                <SceneInsertControl label={index === project.scenes.length - 1 ? "＋ シーンを追加" : "＋ シーンを挿入"} onInsert={() => onAddScene(index === project.scenes.length - 1 ? undefined : project.scenes[index + 1]?.id)} />
              </Fragment>
            ))}
          </>
        )}
      </div>
      {menu && <LineContextMenu state={menu} project={project} props={props} onClose={() => setMenu(null)} />}
    </section>
  );
}
