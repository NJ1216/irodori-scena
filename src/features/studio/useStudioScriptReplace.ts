import type { DialogueLine } from "../../types";
import type { StudioState } from "./useStudioState";

type ReplaceModel = Pick<StudioState, "editSession" | "setNotice"> & { queueAutoRender: (lineId: string) => void };
export function useStudioScriptReplace(model: ReplaceModel) {
  return async function replaceLineTexts(updates: Map<string, Pick<DialogueLine, "text" | "pronunciations">>) {
    if (!model.editSession.savedProject() || !updates.size) return;
    const operation = model.editSession.capture();
    updates.forEach((patch, lineId) => {
      model.editSession.draftLine(lineId, patch);
      model.editSession.commitLine(lineId);
    });
    if ((await model.editSession.save(`${updates.size}行の本文を置換しました。`, "置換を保存できませんでした")) && model.editSession.isCurrent(operation)) updates.forEach((_, lineId) => model.queueAutoRender(lineId));
  };
}
