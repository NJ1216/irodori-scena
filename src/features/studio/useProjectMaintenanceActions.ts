import { api } from "../../api";
import { releaseProjectSwitchBusy } from "./projectSwitchGuard";
import type { CharacterActionModel } from "./studioCharacterActionTypes";

export function useProjectMaintenanceActions(model: CharacterActionModel) {
  const { project, editSession, setWorkspace, setNotice, setBusy, setAutoGenerateEnabled, autoGenerateEnabledRef, autoRenderQueue, clearTakesConfirm, setClearTakesConfirm, stop } = model;
  async function createNewProject() {
    stop();
    setBusy("new-project");
    let switched = false;
    try {
      const result = await editSession.runServer(
        () => api.createNewProject(),
        (value) => editSession.replace(value.project),
      );
      if (!result) return;
      setWorkspace(result.workspace);
      autoRenderQueue.current = [];
      autoGenerateEnabledRef.current = true;
      setAutoGenerateEnabled(true);
      window.dispatchEvent(new Event("scena-llm-usage-reset"));
      setNotice("新規プロジェクトを作成しました。グローバルキャストは引き続き利用できます。");
      switched = true;
    } catch (error) {
      setNotice(`新規プロジェクトを作成できませんでした: ${(error as Error).message}`);
    } finally {
      if (switched) releaseProjectSwitchBusy(setBusy, "new-project");
      else setBusy(null);
    }
  }
  async function clearAllTakes(force = false) {
    if (!project) return;
    if (!force && !clearTakesConfirm) {
      setClearTakesConfirm(true);
      return;
    }
    const takeCount = project.scenes.flatMap((scene) => scene.lines).reduce((count, line) => count + line.takes.length, 0);
    stop();
    setBusy("clear-takes");
    try {
      const next = await editSession.requestProject(() => api.clearAllTakes());
      if (!next) return;
      setAutoGenerateEnabled(false);
      autoGenerateEnabledRef.current = false;
      autoRenderQueue.current = [];
      setNotice(`${takeCount} 件の生成テイクを削除しました。台本とキャストは残り、自動生成はOFFになりました。`);
    } catch (error) {
      setNotice(`生成テイクを削除できませんでした: ${(error as Error).message}`);
    } finally {
      setClearTakesConfirm(false);
      setBusy(null);
    }
  }
  return { createNewProject, clearAllTakes };
}
