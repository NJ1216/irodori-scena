import { useRef } from "react";
import { api } from "../../api";
import type { StudioProject } from "../../types";
import { ApiError } from "../../api-error";
import { mergeProjectValue, projectMergeConflicts } from "./projectSessionMerge";
import { inferSaveIntent, type SaveIntent } from "./projectSaveIntent";

export function useProjectPersistenceState() {
  const projectSaveQueue = useRef<Promise<void>>(Promise.resolve());
  const projectSaveVersion = useRef(0);
  const projectSavedVersion = useRef(0);
  const projectSavePendingCount = useRef(0);
  const projectSaveRunning = useRef(false);
  const projectSavePaused = useRef(false);
  const projectSaveFailureReason = useRef<string | null>(null);
  const confirmedProject = useRef<StudioProject | null>(null);
  const projectSavePauseRelease = useRef<(() => void) | null>(null);
  const projectSavePending = useRef<{
    version: number;
    snapshot: StudioProject;
    successMessage: string;
    failurePrefix: string;
    intent: SaveIntent;
    onSaved?: (saved: StudioProject) => void;
    waiters: Array<(saved: boolean) => void>;
  } | null>(null);
  return {
    projectSaveQueue,
    projectSaveVersion,
    projectSavedVersion,
    projectSavePendingCount,
    projectSaveRunning,
    projectSavePaused,
    projectSaveFailureReason,
    confirmedProject,
    projectSavePauseRelease,
    projectSavePending,
  };
}

export type ProjectPersistenceState = ReturnType<typeof useProjectPersistenceState>;
type PersistenceModel = ProjectPersistenceState & { setNotice: (message: string) => void };
type PendingSave = NonNullable<ProjectPersistenceState["projectSavePending"]["current"]>;

async function persist(snapshot: StudioProject, intent: SaveIntent) {
  if (intent.kind === "full") return api.saveProject(snapshot);
  const result = intent.kind === "metadata" ? await api.patchProjectMetadata(snapshot.revision, intent.changes) : intent.kind === "settings" ? await api.patchProjectSettings(snapshot.revision, intent.changes) : await api.patchProjectLine(intent.lineId, snapshot.revision, intent.changes);
  if (intent.kind === "line" && !Object.hasOwn(intent.changes, "selectedTakeId") && ["text", "stageDirection", "characterId", "speechRate"].some((key) => Object.hasOwn(intent.changes, key))) {
    const scenes = snapshot.scenes.map((scene) => ({ ...scene, lines: scene.lines.map((line) => (line.id === intent.lineId ? { ...line, selectedTakeId: null } : line)) }));
    return { ...snapshot, scenes, revision: result.revision };
  }
  return { ...snapshot, revision: result.revision };
}

async function resolveRevisionConflict(model: PersistenceModel, pending: PendingSave, error: unknown) {
  const detail = error instanceof ApiError && error.code === "project_revision_conflict" ? (error.detail as { currentProject?: StudioProject }) : null;
  const current = detail?.currentProject;
  const base = model.confirmedProject.current;
  if (!current || !base || current.id !== pending.snapshot.id || current.id !== base.id) return null;
  const conflicts = projectMergeConflicts(base, pending.snapshot, current);
  const merged = { ...(mergeProjectValue(base, pending.snapshot, current) as StudioProject), revision: current.revision };
  model.confirmedProject.current = current;
  if (conflicts.length > 0) {
    pending.onSaved?.(merged);
    model.setNotice("同じ項目が別の変更でも更新されました。入力を保持したため、内容を確認してもう一度保存してください。");
    return false;
  }
  const response = await api.saveProject(merged);
  model.confirmedProject.current = response;
  pending.onSaved?.(response);
  model.projectSavedVersion.current = pending.version;
  model.projectSaveFailureReason.current = null;
  model.setNotice(pending.successMessage);
  return true;
}

export function queueProjectSave(model: PersistenceModel, snapshot: StudioProject, successMessage: string, failurePrefix = "保存できませんでした", onSaved?: (saved: StudioProject) => void) {
  const version = model.projectSaveVersion.current + 1;
  model.projectSaveVersion.current = version;
  model.projectSavePendingCount.current += 1;
  const mutable = model as PersistenceModel & Partial<ProjectPersistenceState>;
  mutable.projectSaveRunning ??= { current: false };
  mutable.projectSavePending ??= { current: null };
  mutable.confirmedProject ??= { current: null };
  const result = new Promise<boolean>((resolve) => {
    const pending = mutable.projectSavePending!.current;
    mutable.projectSavePending!.current = { version, snapshot, intent: inferSaveIntent(model.confirmedProject.current, snapshot), successMessage, failurePrefix, onSaved, waiters: [...(pending?.waiters ?? []), resolve] };
  });
  if (!mutable.projectSaveRunning.current && !model.projectSavePaused?.current) {
    mutable.projectSaveRunning.current = true;
    model.projectSaveQueue.current = drainProjectSaves(mutable);
  }
  return result;
}

async function drainProjectSaves(model: PersistenceModel & Partial<ProjectPersistenceState>) {
  while (model.projectSavePending?.current) {
    const pending = model.projectSavePending.current;
    model.projectSavePending.current = null;
    let saved = false;
    try {
      const response = await persist(pending.snapshot, pending.intent);
      model.confirmedProject!.current = response;
      pending.onSaved?.(response);
      model.projectSavedVersion.current = pending.version;
      model.setNotice(pending.successMessage);
      model.projectSaveFailureReason.current = null;
      saved = true;
    } catch (error) {
      try {
        const resolved = await resolveRevisionConflict(model as PersistenceModel, pending, error);
        saved = resolved === true;
        if (resolved === null) {
          model.projectSaveFailureReason.current = (error as Error).message;
          model.setNotice(`${pending.failurePrefix}: ${(error as Error).message}`);
        } else if (resolved === false) {
          model.projectSaveFailureReason.current = "同じ項目が別の変更でも更新されました。内容を確認して保存してください。";
        }
      } catch (retryError) {
        model.projectSaveFailureReason.current = (retryError as Error).message;
        model.setNotice(`${pending.failurePrefix}: ${(retryError as Error).message}`);
      }
    } finally {
      model.projectSavePendingCount.current -= pending.waiters.length;
      pending.waiters.forEach((resolve) => resolve(saved));
    }
  }
  if (model.projectSaveRunning) model.projectSaveRunning.current = false;
}

export function discardPendingProjectSaves(model: ProjectPersistenceState) {
  const pending = model.projectSavePending.current;
  model.projectSavePending.current = null;
  if (pending) {
    model.projectSavePendingCount.current -= pending.waiters.length;
    pending.waiters.forEach((resolve) => resolve(false));
  }
  if (!model.projectSaveRunning.current) {
    model.projectSaveVersion.current = 0;
    model.projectSavedVersion.current = 0;
  }
}

export function pauseProjectSaves(model: ProjectPersistenceState) {
  model.projectSavePaused.current = true;
  model.projectSaveQueue.current = new Promise<void>((resolve) => {
    model.projectSavePauseRelease.current = resolve;
  });
}

export function resumeProjectSaves(model: PersistenceModel) {
  model.projectSavePaused.current = false;
  model.projectSavePauseRelease.current?.();
  model.projectSavePauseRelease.current = null;
  if (model.projectSavePending.current && !model.projectSaveRunning.current) {
    model.projectSaveRunning.current = true;
    model.projectSaveQueue.current = drainProjectSaves(model);
  }
}

export async function waitForProjectPersistence(model: ProjectPersistenceState) {
  while (model.projectSavePendingCount.current > 0) {
    const pending = model.projectSaveQueue.current;
    await pending;
    if (pending === model.projectSaveQueue.current) break;
  }
  return model.projectSavedVersion.current === model.projectSaveVersion.current;
}

export function isProjectPersistencePending(model: ProjectPersistenceState) {
  return model.projectSavePendingCount.current > 0;
}
