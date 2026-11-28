import { api } from "../../api";
import type { DialogueLine, StudioProject } from "../../types";
import { confirmDestructiveAction, selectedTake } from "../shared/studio-utils";
import type { StudioCharacterActions } from "./useStudioCharacterActions";
import type { StudioPlaybackActions } from "./useStudioPlayback";
import type { StudioLineActions } from "./useStudioLineActions";
import type { StudioState } from "./useStudioState";
import { clearPreparedScriptLineSnapshots, prepareScriptLineSnapshots, waitForScriptLineSnapshots } from "../script/scriptLineCapture";
import { beginScriptLineDeletion } from "../script/scriptLineDeletionMotion";
import { lineRenderSignature } from "./renderJobQueue";
import type { SelectedLineGenerationBatch } from "./selectedLineGenerationBatch";

type SelectedLine = { sceneId: string; line: DialogueLine };
type SelectedLineActionsModel = Pick<
  StudioState,
  | "projectRef"
  | "editSession"
  | "selectedLineIds"
  | "selectedLineIdsRef"
  | "busy"
  | "busyRef"
  | "setBusy"
  | "setNotice"
  | "setStatusNotice"
  | "setSelectedLineIds"
  | "setSelectionAnchorLineId"
  | "setFocusedLineId"
  | "setBatchGeneratingLineId"
  | "stopRef"
  | "autoRenderInProgress"
  | "autoRenderPriorityActive"
  | "reconcileAutoRenderQueueRef"
  | "continuousPlayback"
  | "playingLineId"
  | "selectedLineGenerationRun"
  | "selectedLineGenerationTaskRef"
  | "selectedLineGenerationCancelRef"
  | "selectedLineGenerationPauseRef"
  | "selectedLineGenerationBatchRef"
  | "selectedLineGenerationActive"
  | "setSelectedLineGenerationActive"
  | "selectedLinePlaybackStopRun"
  | "selectedLinePlaybackPending"
> &
  Pick<StudioCharacterActions, "deleteLine"> & { runWithAutoRenderPriority: (action: () => Promise<void>) => Promise<void> } & Pick<StudioPlaybackActions, "playSelectedLines"> &
  Pick<StudioLineActions, "applyGeneratedTake">;

function selectedLines(project: StudioProject, ids: string[]): SelectedLine[] {
  const idSet = new Set(ids);
  return project.scenes.flatMap((scene) => scene.lines.filter((line) => idSet.has(line.id)).map((line) => ({ sceneId: scene.id, line })));
}

function historyGroupFor(lines: SelectedLine[]) {
  return lines.length > 1 ? crypto.randomUUID() : undefined;
}

export function selectedActionLineIds(project: StudioProject, selectedIds: string[], sourceLineId: string | null) {
  const allIds = project.scenes.flatMap((scene) => scene.lines.map((line) => line.id));
  const targets = sourceLineId && !selectedIds.includes(sourceLineId) ? new Set([sourceLineId]) : new Set(selectedIds.length ? selectedIds : sourceLineId ? [sourceLineId] : []);
  return allIds.filter((lineId) => targets.has(lineId));
}

function eligibleLines(lines: SelectedLine[]) {
  return lines.filter(({ line }) => Boolean(line.enabled !== false && line.text.trim() && line.characterId));
}

async function generateLine(line: DialogueLine, quality: StudioProject["settings"]["quality"], mode: "append" | "replace", historyGroupId?: string) {
  if (mode === "replace") return api.regenerateLine(line.id, quality, true, undefined, undefined, historyGroupId);
  return api.generateLine(line.id, quality, true, undefined, undefined, historyGroupId);
}

function waitForPaint() {
  return new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
}

async function deleteSelectedLines(model: SelectedLineActionsModel, sourceLineId: string | null = null, immediate = false) {
  const { projectRef, selectedLineIds, busy, setBusy, setNotice, stopRef, setSelectedLineIds, setSelectionAnchorLineId, setFocusedLineId } = model;
  const project = projectRef.current;
  const lines = project ? selectedLines(project, selectedActionLineIds(project, selectedLineIds, sourceLineId)) : [];
  if (!project || !lines.length || busy) return;
  if (lines.length === 1 && !immediate) {
    const [{ sceneId, line }] = lines;
    await model.deleteLine(sceneId, line);
    return;
  }
  if (!immediate && !confirmDestructiveAction("delete-selected-lines", setNotice, `${lines.length} 行の発話行と保存済みテイクを削除します。`, "削除", `${lines.length} 行の発話行を削除しますか？`, "保存済みテイクも削除されます。")) {
    prepareScriptLineSnapshots(lines.map(({ line }) => line.id));
    return;
  }
  await model.runWithAutoRenderPriority(async () => {
    stopRef.current();
    setBusy("delete-selected-lines");
    let motion: ReturnType<typeof beginScriptLineDeletion> | null = null;
    try {
      const removed = new Set(lines.map(({ line }) => line.id));
      await waitForScriptLineSnapshots([...removed]);
      motion = beginScriptLineDeletion([...removed]);
      setSelectedLineIds([]);
      setSelectionAnchorLineId(null);
      setFocusedLineId(null);
      const next = await model.editSession.optimisticProject(
        () => api.deleteLines([...removed]),
        (current) => ({ ...current, scenes: current.scenes.map((scene) => ({ ...scene, lines: scene.lines.filter((line) => !removed.has(line.id)) })) }),
      );
      if (!next) {
        motion.rollback();
        return;
      }
      motion.complete();
      model.reconcileAutoRenderQueueRef.current(model.editSession.serverRevision);
      setNotice(`${lines.length} 行を削除しました。`);
    } catch (error) {
      motion?.rollback();
      clearPreparedScriptLineSnapshots();
      setNotice(`選択した発話行を削除できませんでした: ${(error as Error).message}`);
    } finally {
      setBusy(null);
    }
  });
}

async function playSelected(model: SelectedLineActionsModel, sourceLineId: string | null) {
  const project = model.projectRef.current;
  if (!project) return;
  const ids = selectedActionLineIds(project, model.selectedLineIdsRef.current, sourceLineId);
  const activeIds = model.playingLineId?.split("|") ?? [];
  if (model.continuousPlayback || ids.some((lineId) => activeIds.includes(lineId))) {
    model.stopRef.current();
    return;
  }
  await model.playSelectedLines(ids);
}

async function cleanupSelectedTakes(model: SelectedLineActionsModel, sourceLineId: string, mode: "unselected" | "all") {
  const project = model.projectRef.current;
  if (!project || model.busyRef.current) return;
  const ids = selectedActionLineIds(project, model.selectedLineIdsRef.current, sourceLineId);
  const lines = selectedLines(project, ids);
  const count = lines.reduce((total, { line }) => total + line.takes.filter((take) => mode === "all" || take.id !== line.selectedTakeId).length, 0);
  if (!count) return model.setNotice("整理するテイクはありません。");
  const label = mode === "all" ? "テイクの初期化" : "未採用テイクの削除";
  model.stopRef.current();
  model.busyRef.current = "cleanup-selected-takes";
  model.setBusy("cleanup-selected-takes");
  try {
    const saved = await model.editSession.requestProject(() => api.cleanupLineTakes(ids, mode));
    if (saved) model.setNotice(`${label}を完了しました（${count} テイク）。`);
  } catch (error) {
    model.setNotice(`${label}に失敗しました: ${(error as Error).message}`);
  } finally {
    model.busyRef.current = null;
    model.setBusy(null);
  }
}

function resumableTarget(project: StudioProject, batch: SelectedLineGenerationBatch) {
  const target = batch.targets[batch.nextIndex];
  const match = selectedLines(project, [target.lineId])[0];
  return { target, match };
}

function currentBatchProject(model: SelectedLineActionsModel, batch: SelectedLineGenerationBatch) {
  const project = model.projectRef.current;
  return project?.id === batch.projectId ? project : null;
}

function invalidBatchInput(project: StudioProject, line: DialogueLine, target: SelectedLineGenerationBatch["targets"][number]) {
  return line.enabled === false || !line.text.trim() || !line.characterId || !project.characters.some((character) => character.id === line.characterId) || lineRenderSignature(project, line) !== target.signature;
}

function invalidBatchReplacement(line: DialogueLine, target: SelectedLineGenerationBatch["targets"][number]) {
  return target.mode === "replace" && (line.selectedTakeId !== target.targetTakeId || !selectedTake(line));
}

function skipBatchTarget(model: SelectedLineActionsModel, batch: SelectedLineGenerationBatch, lineId: string, reason: string) {
  batch.skipped += 1;
  batch.nextIndex += 1;
  model.setNotice(`${lineId} は${reason}ため除外しました。`);
}

function queueBatchPlayback(model: SelectedLineActionsModel, lineId: string, generationRun: number, playbackStopRun: number, playback: Promise<void>) {
  return playback.then(() => (model.selectedLineGenerationRun.current === generationRun && model.selectedLinePlaybackStopRun.current === playbackStopRun ? model.playSelectedLines([lineId]) : undefined));
}

async function processBatchRows(model: SelectedLineActionsModel, batch: SelectedLineGenerationBatch, generationRun: number, playbackStopRun: number) {
  let playback = Promise.resolve();
  while (batch.nextIndex < batch.targets.length) {
    if (model.selectedLineGenerationRun.current !== generationRun) break;
    const current = currentBatchProject(model, batch);
    if (!current) break;
    const { target, match } = resumableTarget(current, batch);
    if (!match) {
      skipBatchTarget(model, batch, target.lineId, "発話行が見つからない");
      continue;
    }
    const { line } = match;
    if (invalidBatchInput(current, line, target)) {
      skipBatchTarget(model, batch, target.lineId, "生成条件が変わった");
      continue;
    }
    if (batch.resumed && line.takes.some((take) => !target.knownTakeIds.includes(take.id))) {
      batch.completedIds.push(line.id);
      batch.nextIndex += 1;
      continue;
    }
    if (invalidBatchReplacement(line, target)) {
      skipBatchTarget(model, batch, target.lineId, "生成条件が変わった");
      continue;
    }
    model.setBatchGeneratingLineId(line.id);
    model.setStatusNotice(`${batch.nextIndex + 1}/${batch.targets.length} 行を${batch.replace ? "上書き" : "新規"}生成しています…`);
    await waitForPaint();
    if (model.selectedLineGenerationRun.current !== generationRun) break;
    const take = await generateLine(line, current.settings.quality, target.mode, batch.historyGroupId);
    if (!take || model.selectedLineGenerationRun.current !== generationRun) break;
    model.applyGeneratedTake(match.sceneId, line.id, take, target.mode === "replace", model.editSession.capture());
    batch.completedIds.push(line.id);
    batch.nextIndex += 1;
    if (batch.playAfter) {
      playback = queueBatchPlayback(model, line.id, generationRun, playbackStopRun, playback);
    }
  }
  return { playback };
}

async function runSelectedGenerationBatch(model: SelectedLineActionsModel, batch: SelectedLineGenerationBatch) {
  const generationRun = model.selectedLineGenerationRun.current + 1;
  const playbackStopRun = model.selectedLinePlaybackStopRun.current;
  model.selectedLineGenerationRun.current = generationRun;
  model.selectedLinePlaybackPending.current = batch.playAfter;
  let playback = Promise.resolve();
  const task = model.runWithAutoRenderPriority(async () => {
    model.busyRef.current = "generate-selected-lines";
    model.setBusy("generate-selected-lines");
    try {
      await model.editSession.runServer(async () => {
        ({ playback } = await processBatchRows(model, batch, generationRun, playbackStopRun));
      });
      if (model.selectedLineGenerationRun.current === generationRun && !batch.paused) {
        model.setStatusNotice(`${batch.completedIds.length} 行を${batch.replace ? "上書き再生成" : "新規生成"}しました${batch.skipped ? `（${batch.skipped} 行を除外）` : ""}。`);
      }
    } catch (error) {
      if (!batch.paused && !batch.cancelled) await model.editSession.requestProject(() => api.project());
      if (model.selectedLineGenerationRun.current === generationRun && !batch.paused) model.setNotice(`${batch.completedIds.length} 行を生成後に停止しました: ${(error as Error).message}`);
    } finally {
      model.setBatchGeneratingLineId(null);
      model.busyRef.current = null;
      model.setBusy(null);
    }
    await playback;
    if (batch.cancelled) model.setNotice("選択行の生成をキャンセルしました。生成済みのテイクは保持します。");
  });
  model.selectedLineGenerationTaskRef.current = task;
  try {
    await task;
  } finally {
    if (model.selectedLineGenerationTaskRef.current === task) model.selectedLineGenerationTaskRef.current = Promise.resolve();
    if (model.selectedLineGenerationRun.current === generationRun && !batch.paused) {
      model.selectedLinePlaybackPending.current = false;
      model.setSelectedLineGenerationActive(false);
      if (model.selectedLineGenerationBatchRef.current === batch) model.selectedLineGenerationBatchRef.current = null;
    }
  }
}

export function useStudioSelectedLineActions(model: SelectedLineActionsModel) {
  const {
    projectRef,
    selectedLineIdsRef,
    busy,
    busyRef,
    setNotice,
    stopRef,
    autoRenderInProgress,
    autoRenderPriorityActive,
    continuousPlayback,
    playingLineId,
    selectedLineGenerationRun,
    selectedLineGenerationTaskRef,
    selectedLineGenerationCancelRef,
    selectedLineGenerationPauseRef,
    selectedLineGenerationBatchRef,
    selectedLineGenerationActive,
    setSelectedLineGenerationActive,
    selectedLinePlaybackPending,
  } = model;
  async function generateSelectedLines(replace: boolean, sourceLineId: string | null = null, playAfter = false) {
    const project = projectRef.current;
    const ids = project ? selectedActionLineIds(project, selectedLineIdsRef.current, sourceLineId) : [];
    const lines = project ? selectedLines(project, ids) : [];
    const eligible = eligibleLines(lines);
    if (!project || !eligible.length || selectedLineGenerationBatchRef.current || selectedLineGenerationActive || autoRenderPriorityActive.current || (busy && !autoRenderInProgress.current)) return;
    if (continuousPlayback || playingLineId) stopRef.current();
    const batch: SelectedLineGenerationBatch = {
      projectId: project.id,
      targets: eligible.map(({ line }) => ({ lineId: line.id, signature: lineRenderSignature(project, line), mode: replace && selectedTake(line) ? "replace" : "append", targetTakeId: line.selectedTakeId, knownTakeIds: line.takes.map((take) => take.id) })),
      nextIndex: 0,
      completedIds: [],
      skipped: lines.length - eligible.length,
      replace,
      playAfter,
      paused: false,
      resumed: false,
      cancelled: false,
      historyGroupId: historyGroupFor(eligible),
    };
    selectedLineGenerationBatchRef.current = batch;
    setSelectedLineGenerationActive(true);
    await runSelectedGenerationBatch(model, batch);
  }
  async function pauseSelectedLineGeneration() {
    const batch = selectedLineGenerationBatchRef.current;
    if (!batch || batch.paused || batch.cancelled) return async () => {};
    batch.paused = true;
    selectedLineGenerationRun.current += 1;
    selectedLinePlaybackPending.current = false;
    stopRef.current();
    try {
      await api.cancelAutoRender();
    } catch (error) {
      setNotice(`生成の中断を確認できませんでした: ${(error as Error).message}`);
    }
    await selectedLineGenerationTaskRef.current;
    return async () => {
      if (batch.cancelled || selectedLineGenerationBatchRef.current !== batch) return;
      if (projectRef.current?.id !== batch.projectId) {
        selectedLineGenerationBatchRef.current = null;
        setSelectedLineGenerationActive(false);
        return;
      }
      batch.paused = false;
      batch.resumed = true;
      batch.historyGroupId = crypto.randomUUID();
      await runSelectedGenerationBatch(model, batch);
    };
  }
  async function cancelSelectedLineGeneration() {
    const batch = selectedLineGenerationBatchRef.current;
    if (!batch && !selectedLineGenerationActive && busyRef.current !== "generate-selected-lines") return;
    if (batch) batch.cancelled = true;
    const task = selectedLineGenerationTaskRef.current;
    selectedLineGenerationRun.current += 1;
    selectedLinePlaybackPending.current = false;
    stopRef.current();
    setSelectedLineGenerationActive(false);
    setNotice("選択行の生成をキャンセルしています…");
    try {
      await api.cancelAutoRender();
    } catch (error) {
      setNotice(`未開始の生成を停止しました。実行中の生成は完了する場合があります: ${(error as Error).message}`);
    }
    await task;
    if (selectedLineGenerationBatchRef.current === batch) selectedLineGenerationBatchRef.current = null;
    setSelectedLineGenerationActive(false);
  }
  selectedLineGenerationCancelRef.current = cancelSelectedLineGeneration;
  selectedLineGenerationPauseRef.current = pauseSelectedLineGeneration;
  return {
    deleteSelectedLines: (sourceLineId: string | null = null) => deleteSelectedLines(model, sourceLineId),
    deleteContextLines: (sourceLineId: string) => deleteSelectedLines(model, sourceLineId, true),
    generateSelectedLines,
    cancelSelectedLineGeneration,
    playSelected: (sourceLineId: string | null = null) => playSelected(model, sourceLineId),
    cleanupSelectedTakes: (sourceLineId: string, mode: "unselected" | "all") => cleanupSelectedTakes(model, sourceLineId, mode),
  };
}
