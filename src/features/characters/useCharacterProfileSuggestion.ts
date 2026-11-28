import { useRef, useState } from "react";
import type { Character, CharacterProfile, LlmConnection, StudioProject } from "../../types";
import { applyCharacterProfileSuggestion, displayNameAfterProfileSuggestion, emptyCharacterProfile, listText } from "../shared/studio-utils";
import { ProfileSuggestionSession } from "./characterProfileSuggestionJob";

type Params = {
  project: StudioProject;
  connection: LlmConnection;
  busy: string | null;
  editing: Character | null;
  editName: string;
  editProfile: string;
  details: () => CharacterProfile;
  setEditName: React.Dispatch<React.SetStateAction<string>>;
  setEditDetails: React.Dispatch<React.SetStateAction<CharacterProfile>>;
  setEditAliases: (value: string) => void;
  setEditFirstPerson: (value: string) => void;
  setEditSecondPerson: (value: string) => void;
  onNotice: (value: string) => void;
  onStatusNotice: (value: string) => void;
  onBusy: (value: string | null) => void;
};

const failure = (error: unknown, session: ProfileSuggestionSession) => {
  if (session.cancelled) return "";
  const message = (error as Error).message;
  return message.startsWith("選択した範囲に空欄の項目がありません") ? message : `AIにキャスト設定を相談できませんでした: ${message}`;
};

export function useCharacterProfileSuggestion(params: Params) {
  const [profileSuggestionOpen, setProfileSuggestionOpen] = useState(false);
  const [profileSuggestionIdea, setProfileSuggestionIdea] = useState("");
  const [profileSuggestionError, setProfileSuggestionError] = useState("");
  const [profileSuggestionProgress, setProfileSuggestionProgress] = useState("");
  const [profileSuggestionMode, setProfileSuggestionMode] = useState<"fill_missing" | "replace_details">("fill_missing");
  const [profileSuggestionScope, setProfileSuggestionScope] = useState<"all" | "profile" | "relations">("all");
  const [profileSuggestionFields, setProfileSuggestionFields] = useState<Set<string>>(new Set());
  const [profileSuggestionRelations, setProfileSuggestionRelations] = useState<Set<string>>(new Set());
  const sessionRef = useRef<ProfileSuggestionSession | null>(null);
  function resetProfileSuggestion() {
    setProfileSuggestionOpen(false);
    setProfileSuggestionIdea("");
    setProfileSuggestionError("");
    setProfileSuggestionMode("fill_missing");
    setProfileSuggestionScope("all");
    setProfileSuggestionFields(new Set());
    setProfileSuggestionRelations(new Set());
  }
  async function suggestCharacterProfile(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!params.editing) return;
    setProfileSuggestionError("");
    const currentDetails = params.details();
    if (!params.connection.model.trim()) return void setProfileSuggestionError("設定ページで既定のLLMモデルを選択してください。");
    params.onBusy("character-profile-suggestion");
    const session = new ProfileSuggestionSession();
    sessionRef.current = session;
    try {
      const result = await session.complete(
        {
          mode: profileSuggestionMode,
          scope: profileSuggestionScope,
          name: params.editName,
          profile: params.editProfile,
          profile_details: currentDetails,
          idea: profileSuggestionIdea,
          other_casts: params.project.characters.filter((character) => character.id !== params.editing?.id).map((character) => ({ id: character.id, name: character.name, profile: character.profile, profile_details: character.profileDetails ?? emptyCharacterProfile() })),
        },
        setProfileSuggestionProgress,
      );
      const merged = applyCharacterProfileSuggestion(currentDetails, result.profileDetails);
      const fields = Object.entries(result.profileDetails)
        .filter(([field, value]) => field !== "castRelations" && value)
        .map(([field]) => field);
      const relations = Object.entries(result.profileDetails.castRelations ?? {}).flatMap(([id, relation]) => (["address", "relationship"] as const).filter((field) => relation[field]?.trim()).map((field) => `${id}:${field}`));
      setProfileSuggestionFields((current) => new Set([...current, ...fields]));
      setProfileSuggestionRelations((current) => new Set([...current, ...relations]));
      params.setEditDetails(merged);
      params.setEditName((current) => displayNameAfterProfileSuggestion(current, merged));
      if (result.profileDetails.aliases) params.setEditAliases(listText(merged.aliases));
      if (result.profileDetails.firstPerson) params.setEditFirstPerson(listText(merged.firstPerson));
      if (result.profileDetails.secondPerson) params.setEditSecondPerson(listText(merged.secondPerson));
      setProfileSuggestionOpen(false);
      setProfileSuggestionIdea("");
      setProfileSuggestionProgress("");
      // The filled fields are visible in the open dialog; only a partial result needs the overlay.
      if (result.incompleteFields.length) params.onNotice(`AIの提案を反映しました。返せなかった${result.incompleteFields.length}項目は現在値を保持しています。`);
      else params.onStatusNotice(profileSuggestionMode === "replace_details" ? "選択した範囲をAIの提案で更新しました。" : "選択した範囲の空欄へAIの提案を反映しました。既存の入力内容は変更していません。");
    } catch (error) {
      setProfileSuggestionError(failure(error, session));
    } finally {
      if (sessionRef.current === session) {
        sessionRef.current = null;
        setProfileSuggestionProgress("");
        params.onBusy(null);
      }
    }
  }
  async function cancelCharacterProfileSuggestion() {
    setProfileSuggestionProgress("キャンセルしています…");
    await sessionRef.current?.cancel();
    setProfileSuggestionOpen(false);
    setProfileSuggestionProgress("");
    params.onBusy(null);
  }
  const suggestedFieldClass = (field: string) => (profileSuggestionFields.has(field) ? "ai-suggested-value" : undefined);
  const clearSuggestedField = (field: string) =>
    setProfileSuggestionFields((current) => {
      if (!current.has(field)) return current;
      const next = new Set(current);
      next.delete(field);
      return next;
    });
  const clearSuggestedRelation = (id: string, field: "address" | "relationship") =>
    setProfileSuggestionRelations((current) => {
      const key = `${id}:${field}`;
      if (!current.has(key)) return current;
      const next = new Set(current);
      next.delete(key);
      return next;
    });
  return {
    profileSuggestionOpen,
    setProfileSuggestionOpen,
    profileSuggestionIdea,
    setProfileSuggestionIdea,
    profileSuggestionError,
    setProfileSuggestionError,
    profileSuggestionProgress,
    profileSuggestionMode,
    setProfileSuggestionMode,
    profileSuggestionScope,
    setProfileSuggestionScope,
    profileSuggestionFields,
    setProfileSuggestionFields,
    profileSuggestionRelations,
    setProfileSuggestionRelations,
    suggestingProfile: false,
    resetProfileSuggestion,
    suggestCharacterProfile,
    cancelCharacterProfileSuggestion,
    suggestedFieldClass,
    clearSuggestedField,
    clearSuggestedRelation,
  };
}
