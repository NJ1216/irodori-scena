import { api } from "../../api";
import type { DialogueLine, Scene, StudioProject } from "../../types";
import { confirmDestructiveAction } from "../shared/studio-utils";
import type { CharacterActionModel } from "./studioCharacterActionTypes";
import { clearPreparedScriptLineSnapshots, prepareScriptLineSnapshots, waitForScriptLineSnapshots } from "../script/scriptLineCapture";
import { beginScriptLineDeletion } from "../script/scriptLineDeletionMotion";
import { clearPreparedScriptSceneSnapshots, waitForScriptSceneSnapshot } from "../script/scriptSceneCapture";
import { beginScriptSceneDeletion } from "../script/scriptSceneDeletionMotion";

function withoutLine(project: StudioProject, sceneId: string, lineId: string): StudioProject {
  return { ...project, scenes: project.scenes.map((scene) => (scene.id === sceneId ? { ...scene, lines: scene.lines.filter((line) => line.id !== lineId) } : scene)) };
}

export function useScriptDeletionActions(model: CharacterActionModel) {
  const { editSession, setNotice, setBusy } = model;
  async function deleteLine(sceneId: string, line: DialogueLine) {
    if (!confirmDestructiveAction(`delete-line-${line.id}`, setNotice, "この発話行と保存済みテイクを削除します。", "削除", "この発話行を削除しますか？", "保存済みテイクも削除されます。")) {
      prepareScriptLineSnapshots([line.id]);
      return;
    }
    await model.runWithAutoRenderPriorityRef.current(async () => {
      setBusy(line.id);
      let motion: ReturnType<typeof beginScriptLineDeletion> | null = null;
      try {
        await waitForScriptLineSnapshots([line.id]);
        motion = beginScriptLineDeletion([line.id]);
        const next = await editSession.optimisticProject(
          () => api.deleteLines([line.id]),
          (current) => withoutLine(current, sceneId, line.id),
        );
        if (!next) {
          motion.rollback();
          return;
        }
        motion.complete();
        model.reconcileAutoRenderQueueRef.current(editSession.serverRevision);
        setNotice("発話行とそのテイクを削除しました。");
      } catch (error) {
        motion?.rollback();
        clearPreparedScriptLineSnapshots();
        setNotice(`発話行を削除できませんでした: ${(error as Error).message}`);
      } finally {
        setBusy(null);
      }
    });
  }
  async function deleteScene(scene: Scene) {
    setBusy(scene.id);
    let motion: ReturnType<typeof beginScriptSceneDeletion> | null = null;
    try {
      await waitForScriptSceneSnapshot(scene.id);
      motion = beginScriptSceneDeletion(scene.id);
      const next = await editSession.optimisticProject(
        () => api.deleteScene(scene.id),
        (current) => ({ ...current, scenes: current.scenes.filter((item) => item.id !== scene.id) }),
      );
      if (!next) {
        motion.rollback();
        return;
      }
      motion.complete();
      setNotice(`「${scene.title}」を削除しました。`);
    } catch (error) {
      motion?.rollback();
      clearPreparedScriptSceneSnapshots();
      setNotice(`シーンを削除できませんでした: ${(error as Error).message}`);
    } finally {
      setBusy(null);
    }
  }
  return { deleteLine, deleteScene };
}
