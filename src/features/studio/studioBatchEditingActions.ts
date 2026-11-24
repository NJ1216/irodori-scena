import { adjustSelectedLineGaps, setSelectedLineGaps } from "../script/lineGapBatch";
import { adjustSelectedLineNumericField, setSelectedLineNumericField, type BatchLineNumericField } from "../script/lineNumericBatch";
import { moveProjectLines, type LineDropTarget } from "../script/lineReorder";
import { setSelectedLineSeeds, type LineSeedPatch } from "../script/lineSeedBatch";
import type { StudioEditingModel } from "./studioEditingModel";
import type { StudioProject } from "../../types";

export function createStudioBatchEditingActions(model: StudioEditingModel, updateProject: (mutator: (current: StudioProject) => StudioProject, message?: string) => void, queueAutoRender: (lineId: string, options?: { targetTakeId?: string; historyBaseRevision?: number }) => void) {
  const adjustLineGaps = (ids: string[], directions: readonly (-1 | 1)[]) => updateProject((project) => adjustSelectedLineGaps(project, ids, directions), "発話間隔を保存しました");
  const setLineGaps = (ids: string[], value: number | undefined) => updateProject((project) => setSelectedLineGaps(project, ids, value), "発話間隔を保存しました");
  function saveNumeric(ids: string[], field: BatchLineNumericField, mutate: (project: StudioProject) => StudioProject) {
    const before = model.projectRef.current;
    if (!before) return;
    const after = mutate(before);
    const previous = new Map(before.scenes.flatMap((scene) => scene.lines).map((line) => [line.id, line]));
    const selected = new Set(ids);
    const changed = after.scenes
      .flatMap((scene) => scene.lines)
      .filter((line) => {
        const old = previous.get(line.id);
        return selected.has(line.id) && old && old[field] !== line[field];
      })
      .map((line) => ({ id: line.id, targetTakeId: previous.get(line.id)?.selectedTakeId ?? undefined }));
    if (after === before) return;
    model.editSession.update(() => after);
    const operation = model.editSession.capture();
    void model.editSession.save("発話設定を保存しました").then((saved) => {
      if (saved && model.editSession.isCurrent(operation) && model.busyRef.current !== "export") {
        const historyBaseRevision = model.editSession.serverRevision;
        changed.forEach(({ id, targetTakeId }) => queueAutoRender(id, { targetTakeId, historyBaseRevision }));
      }
    });
  }
  const adjustLineNumericField = (ids: string[], field: BatchLineNumericField, directions: readonly (-1 | 1)[]) => saveNumeric(ids, field, (project) => adjustSelectedLineNumericField(project, ids, field, directions));
  const setLineNumericField = (ids: string[], field: BatchLineNumericField, value: number | undefined) => saveNumeric(ids, field, (project) => setSelectedLineNumericField(project, ids, field, value));
  const setLineSeeds = (ids: string[], patch: LineSeedPatch) => updateProject((project) => setSelectedLineSeeds(project, ids, patch), "Seed設定を保存しました");
  function moveLines(ids: string[], target: LineDropTarget) {
    const current = model.editSession.savedProject();
    if (!current) return;
    const next = moveProjectLines(current, ids, target);
    if (next === current) return;
    model.editSession.update(() => next);
    void model.editSession.save("発話行を移動しました");
  }
  return { adjustLineGaps, setLineGaps, adjustLineNumericField, setLineNumericField, setLineSeeds, moveLines };
}
