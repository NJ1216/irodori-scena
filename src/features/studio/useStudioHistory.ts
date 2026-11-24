import { primaryModifier } from "../shared/platform";
/* eslint-disable react-hooks/set-state-in-effect -- This component synchronizes controlled drafts, imperative media, or stable lifecycle owners at explicit boundaries. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, HISTORY_APPLIED_EVENT, HISTORY_CHANGED_EVENT, type HistoryScope } from "../../api";
import type { StudioState } from "./useStudioState";
import { cancelScriptLineRestoration, prepareScriptLineRestoration } from "../script/scriptLineRestorationMotion";
import type { Tab } from "./types";

type Scope = HistoryScope;
type Status = { canUndo: boolean; canRedo: boolean; busy: boolean };
const blank: Status = { canUndo: false, canRedo: false, busy: false };

function scopeFor(tab: Tab): Scope | null {
  if (tab === "draft") return "script";
  return tab === "script" || tab === "characters" || tab === "pronunciation" ? tab : null;
}

type GenerationHistoryControl = Partial<Pick<StudioState, "autoRenderActiveLineId" | "autoRenderInProgress" | "runWithAutoRenderPriorityRef" | "reconcileAutoRenderQueueRef" | "selectedLineGenerationActive" | "selectedLineGenerationCancelRef" | "selectedLineGenerationPauseRef">>;
type HistoryModel = Pick<StudioState, "tab" | "busy" | "editSession" | "setNotice"> & GenerationHistoryControl;

async function restoreHistory(model: HistoryModel, scope: Scope, direction: "undo" | "redo") {
  const { editSession } = model;
  const restore = () =>
    editSession.runServer(
      async () => ({ status: await api.changeHistory(scope, direction), project: await api.project() }),
      (value, operation) => {
        if (scope === "script" && direction === "undo") prepareScriptLineRestoration(editSession.savedProject(), value.project);
        else cancelScriptLineRestoration();
        if (!editSession.restore(operation, value.project)) cancelScriptLineRestoration();
      },
    );
  const result = await restore();
  if (result) model.reconcileAutoRenderQueueRef?.current();
  return result;
}

async function refreshAfterFailedRestore(model: HistoryModel) {
  try {
    await model.editSession.requestProject(() => api.project());
    return true;
  } catch (error) {
    await model.selectedLineGenerationCancelRef?.current();
    model.setNotice(`履歴復元後の生成を再開できません: ${(error as Error).message}`);
    return false;
  }
}

export function useStudioHistory(model: HistoryModel) {
  const { tab, busy, setNotice } = model;
  const [applying, setApplying] = useState(false);
  const applyingRef = useRef(false);
  const [statuses, setStatuses] = useState<Record<Scope, Status>>({
    script: blank,
    characters: blank,
    pronunciation: blank,
  });
  const scope = scopeFor(tab);
  const autoRenderBusy = model.autoRenderInProgress?.current && busy === model.autoRenderActiveLineId?.current;
  const selectedGenerationActive = busy === "generate-selected-lines" || model.selectedLineGenerationActive === true;
  const selectedGenerationBusy = scope === "script" && selectedGenerationActive;
  const blocked = Boolean(busy && !autoRenderBusy && busy !== "generate-selected-lines");
  const refresh = useCallback(
    async (target = scope) => {
      if (!target) return;
      const status = await api.historyStatus(target);
      setStatuses((current) => ({ ...current, [target]: status }));
    },
    [scope],
  );
  useEffect(() => {
    void refresh().catch(() => undefined);
  }, [refresh]);
  useEffect(() => {
    const refreshAfterMutation = (event: Event) => {
      if (!(event instanceof CustomEvent) || event.detail !== scope) return;
      void refresh(scope).catch(() => undefined);
    };
    window.addEventListener(HISTORY_CHANGED_EVENT, refreshAfterMutation);
    return () => window.removeEventListener(HISTORY_CHANGED_EVENT, refreshAfterMutation);
  }, [refresh, scope]);
  const apply = useCallback(
    async (direction: "undo" | "redo") => {
      if (!scope || blocked || applyingRef.current) return;
      applyingRef.current = true;
      setApplying(true);
      let resumeSelected: (() => Promise<void>) | undefined;
      let mayResume = true;
      try {
        const priority = model.runWithAutoRenderPriorityRef?.current ?? (<T>(action: () => Promise<T>) => action());
        const result = await priority(async () => {
          if (direction === "undo" && selectedGenerationBusy) await model.selectedLineGenerationCancelRef?.current();
          else if (scope !== "script" && selectedGenerationActive) resumeSelected = await model.selectedLineGenerationPauseRef?.current();
          return restoreHistory(model, scope, direction);
        });
        if (!result) return;
        setStatuses((current) => ({ ...current, [scope]: result.status }));
        window.dispatchEvent(new CustomEvent<HistoryScope>(HISTORY_APPLIED_EVENT, { detail: scope }));
        setNotice(direction === "undo" ? "変更を元に戻しました。" : "変更をやり直しました。");
      } catch (error) {
        setNotice(`履歴を復元できません: ${(error as Error).message}`);
        if (resumeSelected) mayResume = await refreshAfterFailedRestore(model);
      } finally {
        applyingRef.current = false;
        setApplying(false);
        if (mayResume && resumeSelected) void resumeSelected().catch((error) => setNotice(`生成を再開できません: ${(error as Error).message}`));
      }
    },
    [blocked, model, scope, selectedGenerationActive, selectedGenerationBusy, setNotice],
  );
  const currentStatus = scope ? statuses[scope] : blank;
  const status = useMemo(() => ({ ...currentStatus, canUndo: currentStatus.canUndo || selectedGenerationBusy, canRedo: currentStatus.canRedo && !selectedGenerationBusy, busy: currentStatus.busy || blocked || applying }), [currentStatus, selectedGenerationBusy, blocked, applying]);
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!primaryModifier(event) || event.key.toLowerCase() !== "z") return;
      const element = document.activeElement;
      if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement || (element instanceof HTMLElement && element.isContentEditable)) return;
      if (status.busy || !scope || (event.shiftKey ? !status.canRedo : !status.canUndo)) return;
      event.preventDefault();
      void apply(event.shiftKey ? "redo" : "undo");
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [apply, scope, status.busy, status.canRedo, status.canUndo]);
  return useMemo(() => ({ historyScope: scope, historyStatus: status, undo: () => apply("undo"), redo: () => apply("redo") }), [apply, scope, status]);
}
