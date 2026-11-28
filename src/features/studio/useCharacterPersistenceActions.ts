import { api } from "../../api";
import type { Character, CharacterProfile, ImagePromptPreferences, VoiceCandidate } from "../../types";
import { deleteCharacter as deleteSavedCharacter } from "./deleteCharacter";
import { adoptCandidateReference, replaceCharacterReference } from "./referenceVoiceActions";
import type { CharacterActionModel } from "./studioCharacterActionTypes";

export function useCharacterPersistenceActions(model: CharacterActionModel) {
  const { editSession, setNotice, setStatusNotice, setBusy, stop } = model;
  async function acceptCandidate(candidate: VoiceCandidate, name: string, profile: string) {
    setBusy(candidate.id);
    try {
      const character = await editSession.requestUpdate(
        () => api.acceptCandidate(candidate.id, name, profile),
        (current, result) => ({ ...current, characters: [...current.characters, result], candidates: current.candidates.filter((item) => item.id !== candidate.id) }),
      );
      if (!character) return false;
      setNotice(`「${character.name}」をキャストに登録しました`);
      return true;
    } catch (error) {
      setNotice(`キャストを登録できませんでした: ${(error as Error).message}`);
      return false;
    } finally {
      setBusy(null);
    }
  }
  const updateCharacterReference = (character: Character, file: File) => replaceCharacterReference({ stop, setBusy, editSession, setNotice, setStatusNotice }, character, file);
  const applyCandidateReference = (character: Character, candidateId: string) => adoptCandidateReference({ stop, setBusy, editSession, setNotice, setStatusNotice }, character, candidateId);
  async function importReference(file: File, name: string, profile: string) {
    setBusy("import-reference");
    try {
      const character = await editSession.requestUpdate(
        () => api.importReference(file, name, profile),
        (current, result) => ({ ...current, characters: [...current.characters, result] }),
      );
      if (!character) return;
      setNotice(`「${character.name}」をWAVからキャストとして登録しました`);
    } catch (error) {
      setNotice(`WAVを登録できませんでした: ${(error as Error).message}`);
    } finally {
      setBusy(null);
    }
  }
  const deleteCharacter = (character: Character, beforeDelete?: () => Promise<void>) => deleteSavedCharacter(model, character, beforeDelete);
  async function reorderCharacters(characterIds: string[]): Promise<boolean> {
    setBusy("reorder-characters");
    try {
      const updated = await editSession.optimisticProject(
        async () => {
          const latest = await api.project();
          return api.reorderCharacters(latest.revision, characterIds);
        },
        (current) => {
          const byId = new Map(current.characters.map((character) => [character.id, character]));
          return { ...current, characters: characterIds.map((id) => byId.get(id)!).filter(Boolean) };
        },
      );
      if (!updated) return false;
      setNotice("キャストの順序を保存しました。");
      return true;
    } catch (error) {
      setNotice(`キャストの順序を保存できませんでした: ${(error as Error).message}`);
      return false;
    } finally {
      setBusy(null);
    }
  }
  async function updateCharacter(character: Character, name: string, profile: string, voiceKeywords: string, profileDetails: CharacterProfile, imagePrompt: string | undefined, imagePromptPreferences: ImagePromptPreferences | undefined): Promise<boolean> {
    setBusy(`edit-${character.id}`);
    try {
      const updated = await editSession.requestUpdate(
        () => api.updateCharacter(character.id, name, profile, voiceKeywords, profileDetails, imagePrompt, imagePromptPreferences, character.lora, character.loraMix),
        (current, result) => ({ ...current, characters: current.characters.map((item) => (item.id === result.id ? result : item)) }),
      );
      if (!updated) return false;
      setNotice(`「${updated.name}」の設定を更新しました。`);
      return true;
    } catch (error) {
      setNotice(`キャスト設定を更新できませんでした: ${(error as Error).message}`);
      return false;
    } finally {
      setBusy(null);
    }
  }
  async function updateCharacterAvatar(character: Character, originalImageBase64: string, thumbnailImageBase64: string): Promise<boolean> {
    setBusy(`avatar-${character.id}`);
    try {
      const updated = await editSession.requestUpdate(
        () => api.updateCharacterAvatar(character.id, originalImageBase64, thumbnailImageBase64),
        (current, result) => ({ ...current, characters: current.characters.map((item) => (item.id === result.id ? result : item)) }),
      );
      if (!updated) return false;
      setStatusNotice(`「${updated.name}」の画像を更新しました。`);
      return true;
    } catch (error) {
      setNotice(`キャラクター画像を保存できませんでした: ${(error as Error).message}`);
      return false;
    } finally {
      setBusy(null);
    }
  }
  async function removeCharacterAvatar(character: Character): Promise<boolean> {
    setBusy(`avatar-${character.id}`);
    try {
      const updated = await editSession.requestUpdate(
        () => api.deleteCharacterAvatar(character.id),
        (current, result) => ({ ...current, characters: current.characters.map((item) => (item.id === result.id ? result : item)) }),
      );
      if (!updated) return false;
      setStatusNotice(`「${updated.name}」の画像を解除しました。`);
      return true;
    } catch (error) {
      setNotice(`キャラクター画像を解除できませんでした: ${(error as Error).message}`);
      return false;
    } finally {
      setBusy(null);
    }
  }
  return { acceptCandidate, updateCharacterReference, applyCandidateReference, importReference, deleteCharacter, reorderCharacters, updateCharacter, updateCharacterAvatar, removeCharacterAvatar };
}
