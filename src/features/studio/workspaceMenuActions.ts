import { api, chooseProjectBackupDestination, chooseProjectFile, chooseProjectSaveDestination, isDesktopRuntime } from "../../api";
import type { StudioState } from "./useStudioState";
import { releaseProjectSwitchBusy } from "./projectSwitchGuard";

type WorkspaceModel = Pick<StudioState, "setBusy" | "setDraftJob" | "setExportJob" | "setGlobalCastUpdates" | "setNotice" | "setWorkspace" | "editSession"> & { stop: () => void };

export function projectBackupDefaultName(workspace: StudioState["workspace"], title: string) {
  if (workspace && !workspace.isScratch && workspace.name.toLowerCase().endsWith(".scena")) return workspace.name;
  const clean = title.replace(/[\\/:\u0000-\u001f]/g, "_").replace(/^[. ]+|[. ]+$/g, "");
  return `${clean || "irodori-scena"}.scena`;
}

export async function backupWorkspaceAction(model: WorkspaceModel & Pick<StudioState, "workspace" | "projectRef">) {
  model.setBusy("backup-workspace");
  try {
    const project = model.projectRef.current;
    if (!project) return;
    if (!model.workspace || model.workspace.isScratch) {
      model.setNotice("先にプロジェクトを保存してください。");
      return;
    }
    const destination = await chooseProjectBackupDestination(projectBackupDefaultName(model.workspace, project.title));
    if (!destination) return;
    const result = await model.editSession.runServer(
      () => api.backupWorkspace(destination),
      (value, operation) => model.editSession.restore(operation, value.project),
    );
    if (!result) return;
    model.setNotice(`「${result.backup.name}」へバックアップしました。現在の保存先は変更していません。`);
  } catch (error) {
    model.setNotice(`プロジェクトをバックアップできませんでした: ${(error as Error).message}`);
  } finally {
    model.setBusy(null);
  }
}

export async function optimizeWorkspaceAction(model: WorkspaceModel & Pick<StudioState, "workspace">) {
  if (!model.workspace || model.workspace.isScratch) {
    model.setNotice("先にプロジェクトを保存してください。");
    return;
  }
  model.setBusy("optimize-workspace");
  model.setNotice("プロジェクトを最適化保存しています…");
  try {
    model.stop();
    const result = await model.editSession.runServer(
      () => api.optimizeWorkspace(),
      (value, operation) => model.editSession.restore(operation, value.project),
    );
    if (!result) return;
    const saved = Math.max(0, result.beforeBytes - result.afterBytes);
    const amount = saved >= 1_000_000 ? `${(saved / 1_000_000).toFixed(1)} MB` : `${Math.round(saved / 1_000)} KB`;
    model.setNotice(saved ? `最適化保存しました。ファイルを約${amount}小さくしました。` : "最適化保存しました。ファイルサイズは変わりませんでした。");
  } catch (error) {
    model.setNotice(`最適化保存できませんでした: ${(error as Error).message}`);
  } finally {
    model.setBusy(null);
  }
}

export async function saveWorkspaceAction(model: WorkspaceModel & Pick<StudioState, "projectRef">) {
  model.setBusy("save-workspace");
  try {
    const selected = isDesktopRuntime ? await chooseProjectSaveDestination(projectBackupDefaultName(null, model.projectRef.current?.title ?? "")) : undefined;
    if (isDesktopRuntime && !selected) return;
    const result = await model.editSession.runServer(
      () => api.saveWorkspace(selected ?? undefined),
      (value, operation) => {
        model.editSession.restore(operation, value.project);
      },
    );
    if (!result) return;
    model.setWorkspace(result.workspace);
    model.setNotice(result.moved ? `「${result.workspace.name}」へ保存しました。以後の編集・生成はこのプロジェクトファイルへ保存されます。` : `「${result.workspace.name}」へ保存しました。`);
  } catch (error) {
    model.setNotice(`プロジェクトを保存できませんでした: ${(error as Error).message}`);
  } finally {
    model.setBusy(null);
  }
}

export async function openWorkspaceAction(model: WorkspaceModel, directPath?: string) {
  model.setBusy("open-workspace");
  let switched = false;
  try {
    const selected = directPath ?? (isDesktopRuntime ? await chooseProjectFile() : undefined);
    if (isDesktopRuntime && !selected) return;
    const result = await model.editSession.runServer(
      () => api.openWorkspace(selected ?? undefined),
      (value) => model.editSession.replace(value.project),
    );
    if (!result) return;
    model.stop();
    model.setWorkspace(result.workspace);
    model.setGlobalCastUpdates(result.globalCastUpdates?.length ? result.globalCastUpdates : null);
    model.setDraftJob(null);
    model.setExportJob(null);
    void api.prepareDerivedAudio().catch(() => undefined);
    model.setNotice(`「${result.workspace.name}」を開きました。以後の編集・生成はこのプロジェクトファイルへ保存されます。`);
    switched = true;
  } catch (error) {
    model.setNotice(`プロジェクトを読み込めませんでした: ${(error as Error).message}`);
  } finally {
    if (switched) releaseProjectSwitchBusy(model.setBusy, "open-workspace");
    else model.setBusy(null);
  }
}
