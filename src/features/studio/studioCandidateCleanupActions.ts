import { api } from "../../api";
import type { VoiceDesignEmotion } from "../../types";
import { clearCandidateState } from "./projectCandidateState";
import type { StudioEditingModel } from "./studioEditingModel";

export function createStudioCandidateCleanupActions(model: StudioEditingModel) {
  async function clearCandidates(showNotice = true) {
    try {
      await clearCandidateState(model.editSession);
      if (showNotice) model.setNotice("未採用の声候補をすべて消去しました。");
    } catch (error) {
      if (showNotice) model.setNotice(`声候補を消去できませんでした: ${(error as Error).message}`);
    }
  }
  async function clearCandidateScope(kind: "baseline" | "emotion", options?: { emotion?: VoiceDesignEmotion; referenceCandidateId?: string }) {
    try {
      const project = await model.editSession.requestProject(() => api.clearCandidateScope(kind, options));
      if (!project) return false;
      model.setNotice(kind === "baseline" ? "基準ボイス候補を消去しました。" : "感情ボイス候補を消去しました。");
      return true;
    } catch (error) {
      model.setNotice(`声候補を消去できませんでした: ${(error as Error).message}`);
      return false;
    }
  }
  return { clearCandidates, clearCandidateScope };
}
