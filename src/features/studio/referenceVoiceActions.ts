import { api } from "../../api";
import type { ProjectEditSession } from "./projectEditSession";
import type { Character, VoiceCandidate, VoiceDesignEmotion } from "../../types";

type ReferenceVoiceModel = {
  stop: () => void;
  setBusy: (value: string | null) => void;
  editSession: ProjectEditSession;
  setNotice: (message: string) => void;
};

export async function replaceCharacterReference(model: ReferenceVoiceModel, character: Character, file: File) {
  model.stop();
  model.setBusy(`reference-${character.id}`);
  try {
    const result = await model.editSession.runServer(
      () => api.updateReference(character.id, file),
      (value, operation) => {
        model.editSession.applyServer(operation, value.project);
      },
    );
    if (!result) return null;
    model.setNotice(`「${character.name}」の参照ボイスを変更しました。${result.invalidatedLines} 行のテイク選択を解除しました。`);
    return result.character;
  } catch (error) {
    model.setNotice(`参照ボイスを変更できませんでした: ${(error as Error).message}`);
    return null;
  } finally {
    model.setBusy(null);
  }
}

export async function adoptCandidateReference(model: ReferenceVoiceModel, character: Character, candidateId: string) {
  model.stop();
  model.setBusy(`reference-${character.id}`);
  try {
    const result = await model.editSession.runServer(
      () => api.applyCandidateReference(character.id, candidateId),
      (value, operation) => {
        model.editSession.applyServer(operation, value.project);
      },
    );
    if (!result) return false;
    model.setNotice(`「${character.name}」へVoiceDesign候補を適用しました。${result.invalidatedLines} 行のテイク選択を解除しました。`);
    return true;
  } catch (error) {
    model.setNotice(`VoiceDesign候補を適用できませんでした: ${(error as Error).message}`);
    return false;
  } finally {
    model.setBusy(null);
  }
}

export async function saveDesignedReference(model: ReferenceVoiceModel, payload: Parameters<typeof api.saveVoiceDesign>[0]) {
  model.setBusy("save-voice-design");
  try {
    const result = await model.editSession.runServer(
      () => api.saveVoiceDesign(payload),
      (value, operation) => {
        model.editSession.applyServer(operation, value.project);
      },
    );
    if (!result) return false;
    model.setNotice(payload.characterId ? `参照ボイスを更新しました。${result.invalidatedLines} 行のテイク選択を解除しました。` : `「${result.character.name}」をキャストに登録しました。`);
    return true;
  } catch (error) {
    model.setNotice(`VoiceDesignを保存できませんでした: ${(error as Error).message}`);
    return false;
  } finally {
    model.setBusy(null);
  }
}

export async function importDesignedReference(model: ReferenceVoiceModel, file: File, options?: { kind: "baseline" | "emotion"; emotion?: VoiceDesignEmotion; referenceCandidateId?: string }): Promise<VoiceCandidate | null> {
  model.setBusy("import-voice-design-reference");
  try {
    const result = await model.editSession.requestUpdate(
      () => api.importVoiceDesignReference(file, options),
      (current, value) => ({ ...current, candidates: [...current.candidates, value.candidate] }),
    );
    if (!result) return null;
    model.setNotice(options?.kind === "emotion" ? "参照ボイスを感情候補として読み込みました。" : "参照ボイスを基準候補として読み込みました。");
    return result.candidate;
  } catch (error) {
    model.setNotice(`参照ボイスを読み込めませんでした: ${(error as Error).message}`);
    return null;
  } finally {
    model.setBusy(null);
  }
}
