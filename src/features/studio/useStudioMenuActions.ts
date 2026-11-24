import type { ProjectMenuAction } from "./projectMenuActionTypes";
import { useProjectMenuActions } from "./projectMenuActions";
import type { StudioJobModel } from "./studioJobModel";
import { backupWorkspaceAction, openWorkspaceAction, optimizeWorkspaceAction, saveWorkspaceAction } from "./workspaceMenuActions";

export function useStudioMenuActions(model: StudioJobModel) {
  async function saveWorkspace(afterAutoStop = false) {
    if (model.busy && !afterAutoStop) return model.setNotice("実行中の処理が完了してから保存してください。");
    await saveWorkspaceAction(model);
  }
  async function openWorkspace(afterAutoStop = false, directPath?: string) {
    if (model.busy && !afterAutoStop) return model.setNotice("実行中の処理が完了してから読み込んでください。");
    await openWorkspaceAction(model, directPath);
  }
  async function backupWorkspace(afterAutoStop = false) {
    if (model.busy && !afterAutoStop) return model.setNotice("実行中の処理が完了してからバックアップしてください。");
    await backupWorkspaceAction(model);
  }
  async function optimizeWorkspace(afterAutoStop = false) {
    if (model.busy && !afterAutoStop) return model.setNotice("実行中の処理が完了してから最適化保存してください。");
    await optimizeWorkspaceAction(model);
  }
  function execute(action: ProjectMenuAction, afterAutoStop = false) {
    if (action === "new") model.setProjectMaintenanceAction("new");
    else if (action === "save") void saveWorkspace(afterAutoStop);
    else if (action === "optimize") void optimizeWorkspace(afterAutoStop);
    else if (action === "open") void openWorkspace(afterAutoStop);
    else if (action === "script-import") model.setScriptImportOpen(true);
    else if (action === "lora-training") model.setTab("lora");
    else if (action === "ai-direction") model.setAiDirectionOpen(true);
    else if (action === "export") {
      if (!model.exportJob || ["completed", "completed_with_warnings", "failed", "cancelled"].includes(model.exportJob.status)) model.setExportJob(null);
      model.setExportDialogOpen(true);
    } else if (action === "cast-export") model.setCastExportDialogOpen(true);
    else if (action === "project-backup") void backupWorkspace(afterAutoStop);
    else model.setProjectMaintenanceAction("takes");
  }
  const menu = useProjectMenuActions({
    autoGenerateEnabled: model.autoGenerateEnabled,
    autoRenderInProgress: model.autoRenderInProgress,
    autoRenderQueue: model.autoRenderQueue,
    pendingAction: model.autoGenerationConflictAction,
    setPendingAction: model.setAutoGenerationConflictAction,
    stopAutoGeneration: model.stopAutoGeneration,
    execute,
    onFailure: (error) => model.setNotice(`自動生成を停止できませんでした: ${error.message}`),
  });
  return { ...menu, backupWorkspace, optimizeWorkspace, saveWorkspace, openWorkspace };
}
