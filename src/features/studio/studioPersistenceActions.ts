import type { DialogueLine, Scene, StudioProject } from "../../types";
import type { StudioEditingModel } from "./studioEditingModel";

const generationFields = ["speechRate", "textCfg", "voiceCfg", "captionCfg"] as const;

export function createStudioPersistenceActions(model: StudioEditingModel, queueAutoRender: (lineId: string, options?: { targetTakeId?: string }) => void) {
  const updateProject = (mutator: (current: StudioProject) => StudioProject, message?: string) => {
    model.editSession.update(mutator);
    void model.editSession.save(message);
  };
  const updateScene = (sceneId: string, patch: Partial<Scene>) => updateProject((current) => ({ ...current, scenes: current.scenes.map((scene) => (scene.id === sceneId ? { ...scene, ...patch } : scene)) }), "シーンを保存しました");
  const updateLine = (_sceneId: string, lineId: string, patch: Partial<DialogueLine>) => {
    const beforeProject = model.projectRef.current;
    const before = beforeProject?.scenes.flatMap((scene) => scene.lines).find((line) => line.id === lineId);
    const targetTakeId = before?.selectedTakeId ?? undefined;
    if (model.editSession.updateLine(lineId, patch)) return;
    const afterProject = model.projectRef.current;
    const after = afterProject?.scenes.flatMap((scene) => scene.lines).find((line) => line.id === lineId);
    const changed = Boolean(before && after && generationFields.some((key) => Object.hasOwn(patch, key) && before[key] !== after[key]));
    const operation = model.editSession.capture();
    void model.editSession.save("台詞を保存しました").then((saved) => {
      if (saved && changed && model.editSession.isCurrent(operation) && model.busyRef.current !== "export") queueAutoRender(lineId, { targetTakeId });
    });
  };
  return { updateProject, updateScene, updateLine, waitForProjectPersistence: model.editSession.waitForPersistence, isProjectPersistencePending: () => model.projectSavePendingCount.current > 0 };
}
