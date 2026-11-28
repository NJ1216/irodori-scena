import { effectiveMix, editableMix } from "../lora/loraMix";
import { useRef, useState } from "react";
import type { Character, CharacterProfile, ImagePromptPreferences } from "../../types";
import { emptyCharacterProfile, listText, listValues } from "../shared/studio-utils";
import { reportCharacterMemoLimit } from "./characterMemo";
import { useInlineValidation } from "../shared/useInlineValidation";

type SaveCallbacks = {
  imagePrompt: string;
  preferences: ImagePromptPreferences;
  onUpdate: (character: Character, name: string, profile: string, voiceKeywords: string, details: CharacterProfile, prompt: string, preferences: ImagePromptPreferences) => Promise<boolean>;
  onRemoveAvatar: (character: Character) => Promise<boolean>;
  onUpdateAvatar: (character: Character, original: string, thumbnail: string) => Promise<boolean>;
};

export function useCharacterEditor(onNotice: (message: string) => void) {
  const [editing, setEditing] = useState<Character | null>(null);
  const [editName, setEditName] = useState("");
  const [editProfile, setEditProfile] = useState("");
  const [editDetails, setEditDetails] = useState<CharacterProfile>(emptyCharacterProfile);
  const [editAliases, setEditAliases] = useState("");
  const [editFirstPerson, setEditFirstPerson] = useState("");
  const [editSecondPerson, setEditSecondPerson] = useState("");
  const [avatarSource, setAvatarSource] = useState<string | null>(null);
  const [editAvatarChange, setEditAvatarChange] = useState<{ original: string; thumbnail: string } | null | undefined>(undefined);
  const avatarInput = useRef<HTMLInputElement>(null);
  const referenceInput = useRef<HTMLInputElement>(null);
  const editValidation = useInlineValidation();
  const editableProfileDetails = (): CharacterProfile => ({ ...editDetails, aliases: listValues(editAliases), firstPerson: listValues(editFirstPerson), secondPerson: listValues(editSecondPerson) });
  function beginEdit(character: Character, prepare: () => void) {
    setEditing({ ...character, loraMix: editableMix(effectiveMix(character)) });
    setEditName(character.name);
    setEditProfile(character.profile);
    setEditDetails(character.profileDetails ?? emptyCharacterProfile());
    setEditAliases(listText(character.profileDetails?.aliases));
    setEditFirstPerson(listText(character.profileDetails?.firstPerson));
    setEditSecondPerson(listText(character.profileDetails?.secondPerson));
    setAvatarSource(null);
    setEditAvatarChange(undefined);
    editValidation.clear();
    prepare();
  }
  function chooseAvatar(file: File | null) {
    if (!file) return;
    if (!file.type.startsWith("image/")) return void editValidation.report("画像ファイルを選択してください。", "avatar");
    editValidation.clear("avatar");
    const reader = new FileReader();
    reader.onload = () => setAvatarSource(typeof reader.result === "string" ? reader.result : null);
    reader.onerror = () => onNotice("画像を読み込めませんでした。");
    reader.readAsDataURL(file);
  }
  async function saveEdit(event: React.FormEvent<HTMLFormElement>, callbacks: SaveCallbacks) {
    event.preventDefault();
    if (!editing) return;
    if (!editName.trim()) return void editValidation.report("キャラクター名を入力してください。", "editName");
    if (reportCharacterMemoLimit(editProfile, editValidation.report, "editProfile")) return;
    const saved = await callbacks.onUpdate({ ...editing, lora: editing.lora?.enabled === false ? null : editing.lora, loraMix: editableMix(effectiveMix(editing)) }, editName, editProfile, editing.voiceKeywords, editableProfileDetails(), callbacks.imagePrompt, callbacks.preferences);
    if (!saved) return;
    if (editAvatarChange === null && !(await callbacks.onRemoveAvatar(editing))) return;
    if (editAvatarChange && !(await callbacks.onUpdateAvatar(editing, editAvatarChange.original, editAvatarChange.thumbnail))) return;
    setEditAvatarChange(undefined);
    setEditing(null);
  }
  const editAvatarPreview = editing ? (editAvatarChange === undefined ? (editing.avatarThumbnailUrl ?? editing.avatarUrl) : (editAvatarChange?.thumbnail ?? "")) : "";
  return {
    editing,
    setEditing,
    editName,
    setEditName: (value: React.SetStateAction<string>) => (setEditName(value), editValidation.clear("editName")),
    editProfile,
    setEditProfile: (value: React.SetStateAction<string>) => (setEditProfile(value), editValidation.clear("editProfile")),
    editValidation,
    editDetails,
    setEditDetails,
    editAliases,
    setEditAliases,
    editFirstPerson,
    setEditFirstPerson,
    editSecondPerson,
    setEditSecondPerson,
    avatarSource,
    setAvatarSource,
    editAvatarChange,
    setEditAvatarChange,
    avatarInput,
    referenceInput,
    editableProfileDetails,
    beginEdit,
    chooseAvatar,
    saveEdit,
    editAvatarPreview,
  };
}
