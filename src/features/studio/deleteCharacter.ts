import { api } from "../../api";
import type { Character } from "../../types";
import { confirmDestructiveAction } from "../shared/destructiveConfirmation";
import type { StudioState } from "./useStudioState";

export async function deleteCharacter(model: Pick<StudioState, "editSession" | "setBusy" | "setNotice">, character: Character, beforeDelete?: () => Promise<void>): Promise<boolean> {
  const { editSession, setBusy, setNotice } = model;
  if (!confirmDestructiveAction(`delete-character-${character.id}`, setNotice, `「${character.name}」を削除します。参照WAVは削除されますが、生成済みテイクは残ります。`, "削除", `「${character.name}」を削除しますか？`, "参照WAVは削除されますが、生成済みテイクは残ります。")) return false;
  setBusy(character.id);
  const operation = editSession.capture();
  try {
    await beforeDelete?.();
    if (!editSession.isCurrent(operation)) return false;
    const next = await editSession.requestProject(() => api.deleteCharacter(character.id));
    if (!next) return false;
    setNotice(`「${character.name}」を削除しました。該当する発話行はキャスト未選択に戻しました。`);
    return true;
  } catch (error) {
    setNotice(`キャストを削除できませんでした: ${(error as Error).message}`);
    return false;
  } finally {
    setBusy(null);
  }
}
