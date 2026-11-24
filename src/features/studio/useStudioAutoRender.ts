import { api } from "../../api";
import { ApiError } from "../../api-error";
import type { StudioLineActions } from "./useStudioLineActions";
import type { StudioPlaybackActions } from "./useStudioPlayback";
import type { StudioState } from "./useStudioState";
import { recordPlaybackRenderEvent } from "./playbackRenderDiagnostics";
import { dequeueRenderJob, isCurrentRenderJob, lineRenderSignature, requeueInterruptedJob, type RenderJob } from "./renderJobQueue";

type AutoRenderModel = Pick<
  StudioState,
  | "autoGenerateEnabledRef"
  | "autoGenerationRequestRef"
  | "autoRenderQueue"
  | "autoRenderInProgress"
  | "autoRenderActiveLineId"
  | "playbackProtectedLineIds"
  | "autoRenderPriorityActive"
  | "autoRenderPriorityDepth"
  | "processAutoRenderQueueRef"
  | "runWithAutoRenderPriorityRef"
  | "reconcileAutoRenderQueueRef"
  | "busyRef"
  | "projectRef"
  | "editSession"
  | "playingLineId"
  | "setBusy"
  | "setNotice"
  | "setStatusNotice"
  | "setAutoGenerateEnabled"
> &
  Pick<StudioLineActions, "applyGeneratedTake"> &
  Pick<StudioPlaybackActions, "stop">;

function autoRenderMessage(job: RenderJob) {
  if (job.mode === "replace") return "発話行の音声を上書き生成しています…";
  return job.cause === "ai-direction" ? "AI演出後の新規テイクを生成しています…" : "発話行の新しいテイクを生成しています…";
}

async function renderAutoTake(job: RenderJob, quality: "turbo" | "fast" | "quality") {
  if (job.mode === "append") return job.historyGroupId ? api.generateLine(job.lineId, quality, true, job.seed, job.historyBaseRevision, job.historyGroupId) : api.generateLine(job.lineId, quality, true, job.seed, job.historyBaseRevision);
  return job.historyGroupId ? api.regenerateLine(job.lineId, quality, true, job.targetTakeId, job.historyBaseRevision, job.historyGroupId) : api.regenerateLine(job.lineId, quality, true, job.targetTakeId, job.historyBaseRevision);
}

async function waitForAutoRenderStop(inProgress: { current: boolean }) {
  while (inProgress.current) await new Promise((resolve) => window.setTimeout(resolve, 25));
}

function autoRenderBlocked(model: Pick<AutoRenderModel, "autoRenderInProgress" | "autoRenderPriorityActive" | "autoGenerateEnabledRef" | "busyRef">) {
  return model.autoRenderInProgress.current || model.autoRenderPriorityActive.current || !model.autoGenerateEnabledRef.current || Boolean(model.busyRef.current);
}

function shouldRequeueAfterPriorityInterruption(error: unknown, enabled: boolean) {
  return enabled && error instanceof ApiError && error.kind === "priority-interruption";
}

function renderTarget(project: AutoRenderModel["projectRef"]["current"], lineId: string) {
  const target = project?.scenes.flatMap((scene) => scene.lines.map((line) => ({ sceneId: scene.id, line }))).find((item) => item.line.id === lineId);
  return target && target.line.enabled !== false && target.line.text.trim() && target.line.characterId && project?.characters.some((character) => character.id === target.line.characterId) ? target : null;
}

function currentRenderTarget(model: AutoRenderModel, job: RenderJob) {
  const project = model.projectRef.current;
  const target = renderTarget(project, job.lineId);
  return project && target && isCurrentRenderJob(project, target.line, job, model.editSession.capture().generation) ? { project, target } : null;
}

async function renderQueuedTake(model: AutoRenderModel, job: RenderJob) {
  if (!(await model.editSession.waitForPersistence())) throw new Error(model.editSession.persistence?.failureReason?.() ?? "プロジェクトを保存できませんでした。");
  const current = model.autoGenerateEnabledRef.current && !model.autoRenderPriorityActive.current && currentRenderTarget(model, job);
  if (!current) return null;
  return renderAutoTake(job, current.project.settings.quality);
}

function isCurrentRenderResult(model: AutoRenderModel, job: RenderJob, operation: ReturnType<AutoRenderModel["editSession"]["capture"]>) {
  if (!model.editSession.isCurrent(operation)) return false;
  const latest = model.projectRef.current;
  const line = latest?.scenes.flatMap((scene) => scene.lines).find((item) => item.id === job.lineId);
  return Boolean(latest && line && lineRenderSignature(latest, line) === job.renderSignature);
}

function recordAutoRenderFailure(model: AutoRenderModel, job: RenderJob, error: unknown, renderStartedAt: number) {
  const detail = { createNewTake: job.mode === "append" };
  if (shouldRequeueAfterPriorityInterruption(error, model.autoGenerateEnabledRef.current)) {
    recordPlaybackRenderEvent({ kind: "auto-render-interrupted", lineId: job.lineId, durationMs: performance.now() - renderStartedAt, detail });
    model.autoRenderQueue.current = requeueInterruptedJob(model.autoRenderQueue.current, job);
  } else {
    recordPlaybackRenderEvent({ kind: "auto-render-failed", lineId: job.lineId, durationMs: performance.now() - renderStartedAt, detail });
    model.setNotice(`この生成要求を完了できませんでした: ${(error as Error).message}`);
  }
}

export function useStudioAutoRender(model: AutoRenderModel) {
  const { autoGenerateEnabledRef, autoGenerationRequestRef, autoRenderQueue, autoRenderInProgress, autoRenderActiveLineId, autoRenderPriorityActive, processAutoRenderQueueRef, busyRef, projectRef, playingLineId, setBusy, setStatusNotice, stop, applyGeneratedTake } = model;

  async function processAutoRenderQueue() {
    if (autoRenderBlocked({ autoRenderInProgress, autoRenderPriorityActive, autoGenerateEnabledRef, busyRef })) return;
    const project = projectRef.current;
    if (!project) return;
    const job = dequeueRenderJob(autoRenderQueue.current, project, model.playbackProtectedLineIds.current);
    if (!job) return;
    const { lineId } = job;
    const createNewTake = job.mode === "append";
    const sessionOperation = model.editSession.capture();
    const targetState = currentRenderTarget(model, job);
    if (!targetState) {
      void processAutoRenderQueue();
      return;
    }
    const { target } = targetState;
    autoRenderInProgress.current = true;
    autoRenderActiveLineId.current = lineId;
    const renderStartedAt = performance.now();
    recordPlaybackRenderEvent({ kind: "auto-render-started", lineId, detail: { createNewTake } });
    setBusy(lineId);
    setStatusNotice(autoRenderMessage(job));
    try {
      if (playingLineId === lineId) stop();
      const take = await renderQueuedTake(model, job);
      if (!take) return;
      if (!isCurrentRenderResult(model, job, sessionOperation)) return;
      applyGeneratedTake(target.sceneId, lineId, take, !createNewTake, sessionOperation);
      recordPlaybackRenderEvent({ kind: "auto-render-completed", lineId, durationMs: performance.now() - renderStartedAt, detail: { createNewTake } });
      setStatusNotice("確定した本文の音声を更新しました。");
    } catch (error) {
      if (!model.editSession.isCurrent(sessionOperation)) return;
      recordAutoRenderFailure(model, job, error, renderStartedAt);
    } finally {
      autoRenderInProgress.current = false;
      autoRenderActiveLineId.current = null;
      setBusy((current) => (current === lineId ? null : current));
      if (model.editSession.isCurrent(sessionOperation) && !autoRenderPriorityActive.current && autoGenerateEnabledRef.current) window.setTimeout(() => void processAutoRenderQueue(), 0);
    }
  }

  async function runWithAutoRenderPriority<T>(action: () => Promise<T>) {
    model.autoRenderPriorityDepth.current += 1;
    autoRenderPriorityActive.current = true;
    try {
      if (autoRenderInProgress.current) {
        const lineId = autoRenderActiveLineId.current ?? undefined;
        const cancellationStartedAt = performance.now();
        recordPlaybackRenderEvent({ kind: "auto-render-cancel-requested", lineId });
        await api.cancelAutoRender();
        recordPlaybackRenderEvent({ kind: "auto-render-cancel-acknowledged", lineId, durationMs: performance.now() - cancellationStartedAt });
        await waitForAutoRenderStop(autoRenderInProgress);
        recordPlaybackRenderEvent({ kind: "auto-render-worker-stopped", lineId, durationMs: performance.now() - cancellationStartedAt });
      }
      return await action();
    } finally {
      model.autoRenderPriorityDepth.current -= 1;
      if (model.autoRenderPriorityDepth.current === 0) {
        autoRenderPriorityActive.current = false;
        void processAutoRenderQueue();
      }
    }
  }

  async function stopAutoGeneration() {
    autoGenerationRequestRef.current += 1;
    autoGenerateEnabledRef.current = false;
    model.setAutoGenerateEnabled(false);
    autoRenderQueue.current = [];
    if (autoRenderInProgress.current) {
      model.setNotice("自動生成を中断しています…");
      await api.cancelAutoRender();
      await waitForAutoRenderStop(autoRenderInProgress);
    }
    model.setNotice("自動生成を停止しました。");
  }

  function reconcileAutoRenderQueue(historyBaseRevision?: number) {
    const project = projectRef.current;
    if (!project) {
      autoRenderQueue.current = [];
      return;
    }
    const generation = model.editSession.capture().generation;
    autoRenderQueue.current = autoRenderQueue.current.flatMap((job) => {
      if (job.projectId !== project.id) return [];
      const target = renderTarget(project, job.lineId);
      if (!target) return [];
      const rebased = { ...job, projectGeneration: generation, interruptionCount: 0, historyBaseRevision: historyBaseRevision ?? (job.historyBaseRevision === undefined ? undefined : model.editSession.serverRevision) };
      return isCurrentRenderJob(project, target.line, rebased, generation) ? [rebased] : [];
    });
  }

  processAutoRenderQueueRef.current = processAutoRenderQueue;
  model.runWithAutoRenderPriorityRef.current = runWithAutoRenderPriority;
  model.reconcileAutoRenderQueueRef.current = reconcileAutoRenderQueue;
  return { processAutoRenderQueue, runWithAutoRenderPriority, stopAutoGeneration };
}

export type StudioAutoRenderActions = ReturnType<typeof useStudioAutoRender>;
