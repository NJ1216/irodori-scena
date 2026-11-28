import type { Character, CharacterProfile, ImagePromptPreferences, LlmConnection, StudioProject, VoiceCandidate, VoiceDesignEmotion } from "../../types";
import type { VoiceDesign } from "./voiceDesign";

export type CharactersViewModelProps = {
  project: StudioProject;
  connection: LlmConnection;
  notice: string;
  busy: string | null;
  onAccept: (candidate: VoiceCandidate, name: string, profile: string) => Promise<boolean>;
  onImport: (file: File, name: string, profile: string) => Promise<void>;
  onUpdate: (character: Character, name: string, profile: string, voiceKeywords: string, profileDetails: CharacterProfile, imagePrompt: string | undefined, imagePromptPreferences: ImagePromptPreferences | undefined) => Promise<boolean>;
  onUpdateReference: (character: Character, file: File) => Promise<Character | null>;
  onApplyCandidateReference: (character: Character, candidateId: string) => Promise<boolean>;
  onUpdateAvatar: (character: Character, original: string, thumbnail: string) => Promise<boolean>;
  onRemoveAvatar: (character: Character) => Promise<boolean>;
  onDelete: (character: Character, beforeDelete?: () => Promise<void>) => Promise<boolean>;
  onReorder: (characterIds: string[]) => Promise<boolean>;
  onGenerateCandidates: (
    keywords: string,
    count: number,
    sampleText: string,
    options?: {
      kind: "baseline" | "emotion";
      emotion?: VoiceDesignEmotion;
      referenceCandidateId?: string;
      speechRate?: number;
      textCfg?: number;
      voiceCfg?: number;
      captionCfg?: number;
      voiceDesign?: VoiceDesign;
    },
  ) => Promise<boolean>;
  onImportVoiceDesignReference: (file: File, options?: { kind: "baseline" | "emotion"; emotion?: VoiceDesignEmotion; referenceCandidateId?: string }) => Promise<VoiceCandidate | null>;
  onSaveVoiceDesign: (payload: { baselineCandidateId: string; emotionCandidateIds: Partial<Record<VoiceDesignEmotion, string>>; name: string; profile: string; voiceKeywords: string; voiceDesign: VoiceDesign; characterId?: string }) => Promise<boolean>;
  onClearCandidates: () => Promise<void>;
  onClearCandidateScope: (kind: "baseline" | "emotion", options?: { emotion?: VoiceDesignEmotion; referenceCandidateId?: string }) => Promise<boolean>;
  onNotice: (text: string) => void;
  /** Header-only notice for results the open dialog already shows; never raises the dialog overlay. */
  onStatusNotice: (text: string) => void;
  onBusy: (value: string | null) => void;
};
