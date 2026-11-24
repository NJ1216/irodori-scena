import type { components } from "../generated/openapi";
import type { QualityPreset, TtsProjectSelection } from "./runtime";
export type LoraReference = {
  assetId: string;
  adapterHash: string;
  baseModelRepo: string;
  baseModelRevision: string;
  enabled: boolean;
};

export type LoraMixEntry = Omit<LoraReference, "enabled"> & { weight: number };
export type LoraMix = { version: 1; baseWeight: number; entries: LoraMixEntry[] };

export type Take = {
  lora?: LoraReference | null;
  loraMix?: LoraMix | null;
  loraExecution?: { mix?: { baseWeight: number; adapters: Array<{ adapterHash: string; weight: number }> } | null; applied: boolean; adapterHash: string | null; baseModelRepo: string; baseModelRevision: string; artifactRepo?: string; artifactRevision?: string; precision?: string } | null;
  id: string;
  characterId?: string;
  audioUrl: string;
  seed: number;
  quality: QualityPreset;
  stageDirection: string;
  durationSeconds?: number;
  /** Requested synthesis duration; distinct from the completed WAV duration. */
  targetDurationSeconds?: number;
  speechRate?: number;
  settings?: {
    speechRate: number;
    steps: number;
    textCfg: number;
    voiceCfg: number;
    captionCfg: number;
  };
  generationSeconds?: number;
  createdAt: number;
  /** Exact pronunciation-applied text sent to TTS. Missing on legacy takes. */
  renderedText?: string;
  ttsConfiguration?: {
    engineCommit: string | null;
    modelRevision: string | null;
    codecRevision: string | null;
    /** Actual decoder distribution, independent of the selected Torch Codec. */
    codecArtifactRepo?: string | null;
    codecArtifactRevision?: string | null;
    codecPrecision?: string | null;
    optimizationProfile: string | null;
    precision?: string | null;
    variantId?: string | null;
    backend?: string | null;
    artifactRepo?: string | null;
    artifactRevision?: string | null;
    route?: string | null;
  };
  ttsPerformance?: { stageTimingsMs: Record<string, number>; fallbackReason: string | null; cache?: Record<string, unknown>; peakVramBytes?: number | null };
};

export type LineGenerationResult = { take: Take; projectRevision: number };

export type DialogueLine = {
  id: string;
  characterId: string;
  text: string;
  /** Line-local readings indexed in Unicode code points in `text`. */
  pronunciations?: LinePronunciation[];
  stageDirection: string;
  takes: Take[];
  selectedTakeId: string | null;
  /** Explicit line-local seed reused for future synthesis. */
  fixedSeed?: number;
  /** Legacy user-entered override; new explicit seeds create a Take instead. */
  manualSeed?: number;
  gapSeconds?: number;
  speechRate?: number;
  /** Optional line-local CFG overrides; omitted values inherit project settings. */
  textCfg?: number;
  voiceCfg?: number;
  captionCfg?: number;
  /** Optional fixed synthesis target; simultaneous cues otherwise link dynamically. */
  targetDurationSeconds?: number;
  /** Omitted by version-1 projects; omission means enabled. */
  enabled?: boolean;
  /** Consecutive lines with the same ID form one simultaneous speech cue. */
  cueId?: string;
  /** Non-negative start time within a simultaneous cue. */
  startOffsetSeconds?: number;
};

export type LinePronunciation = {
  id: string;
  start: number;
  end: number;
  text: string;
  reading: string;
};

export type Scene = {
  id: string;
  title: string;
  lines: DialogueLine[];
};

export type Character = {
  sampleText?: string | null;
  lora?: LoraReference | null;
  loraMix?: LoraMix | null;
  id: string;
  name: string;
  profile: string;
  profileDetails?: CharacterProfile;
  voiceKeywords: string;
  voiceDesign?: import("../features/characters/voiceDesign").VoiceDesign;
  /** An editable prompt for an external character-image generator. */
  imagePrompt?: string;
  imagePromptPreferences?: ImagePromptPreferences;
  /** Source image kept for full-size viewing in the cast notebook. */
  avatarOriginalUrl?: string;
  /** 189 x 189 cropped image used wherever an avatar icon is shown. */
  avatarThumbnailUrl?: string;
  /** @deprecated Use avatarThumbnailUrl. Retained for old project data. */
  avatarUrl?: string;
  avatarVersion?: number;
  /** Cache buster incremented whenever the managed reference WAV changes. */
  referenceVersion?: number;
  referenceAudioUrl: string;
  referenceFile: string;
  createdAt: number;
};

export type CastImportItem = {
  key: string;
  path: string;
  status: "new" | "identical" | "conflict";
  incoming: Character & { audioHash?: string };
  existing: (Character & { audioHash?: string }) | null;
};

export type CastImportPreparation = {
  warnings?: string[];
  sessionId: string;
  items: CastImportItem[];
  errors: Array<{ path: string; status: "invalid"; error: string }>;
  expiresInSeconds: number;
};

export type ImagePromptPreferences = {
  output_language: "english" | "japanese";
  subject?: string;
  secondary_hair_color_enabled?: boolean;
  secondary_hair_color?: string;
  secondary_hair_color_style?: string;
  hair_color: string;
  eye_color: string;
  eye_style: string;
  hair_length: string;
  hairstyle: string;
  expression: string;
  outfit: string;
  outfit_impression: string;
  occupation?: string;
  accessory: string;
  style: string;
  composition: string;
  screen_effect?: string;
  background: string;
  skin_tone: string;
  hair_texture: string;
  bangs: string;
  facial_hair: string;
  body_build: string;
  age_impression: string;
  face_contour: string;
  eyebrow_shape: string;
  makeup: string;
  height: string;
  bust_size: string;
  freckles_moles: string;
  scars: string;
  tattoos: string;
  request: string;
  pose?: string;
  gestures?: string[];
  camera_angle?: string;
  background_color?: string;
  background_gradient_color1?: string;
  background_gradient_color2?: string;
  background_gradient_direction?: string;
};

/** Body of the image-prompt suggestion request: stored preferences (secondary hair colour required) plus the cast context. */
export type ImagePromptSuggestionRequest = ImagePromptPreferences &
  Required<Pick<ImagePromptPreferences, "secondary_hair_color_enabled" | "secondary_hair_color" | "secondary_hair_color_style">> & {
    name?: string;
    profile?: string;
    profile_details?: CharacterProfile;
  };

/** Body of the profile-suggestion request and its background job. */
export type ProfileSuggestionRequest = {
  name: string;
  profile: string;
  profile_details: CharacterProfile;
  idea: string;
  mode?: "fill_missing" | "replace_details";
  scope?: "all" | "profile" | "relations";
  other_casts: Array<{ id: string; name: string; profile: string; profile_details: CharacterProfile }>;
};

export type CharacterProfile = {
  familyName?: string;
  familyNameKana?: string;
  givenName?: string;
  givenNameKana?: string;
  aliases?: string[];
  age?: string;
  bloodType?: string;
  birthDate?: string;
  birthplace?: string;
  residence?: string;
  gender?: string;
  role?: string;
  firstPerson?: string[];
  secondPerson?: string[];
  defaultAddressBasis?: string;
  defaultHonorific?: string;
  defaultAddressNote?: string;
  skills?: string;
  hobbies?: string;
  likes?: string;
  dislikes?: string;
  personality?: string;
  speechStyle?: string;
  background?: string;
  otherRelationships?: string;
  castRelations?: Record<string, CastRelation>;
};

export type CastRelation = {
  address?: string;
  relationship?: string;
};

export type PronunciationDictionaryEntry = {
  id: string;
  term: string;
  reading: string;
  source: "manual" | "cast";
  characterId?: string | null;
  sourceKeys: string[];
  suggestedReading: string;
  userEdited: boolean;
  locked: boolean;
  scopes?: Array<"global" | "project">;
  globalId?: string | null;
  projectId?: string | null;
  merged?: boolean;
  hasDifferentVersion?: boolean;
};

export type PronunciationDictionaryChange = {
  operation: "add-manual" | "update-manual" | "delete-manual" | "add-cast" | "update-cast" | "delete-cast" | "suggest-manual" | "suggest-cast" | "toggle-scope";
  entry_id?: string;
  character_id?: string;
  term?: string;
  reading?: string;
  scope?: "global" | "project";
  scopes?: Array<"global" | "project">;
  enabled?: boolean;
  replace_conflict?: boolean;
  global_id?: string;
  project_id?: string;
  locked?: boolean;
};

export type PronunciationDictionaryChangeResult = {
  entries: PronunciationDictionaryEntry[];
  affectedLineIds: string[];
};

export type VoiceCandidate = {
  id: string;
  keywords: string;
  voiceDesign?: import("../features/characters/voiceDesign").VoiceDesign;
  sampleText: string;
  seed: number;
  audioUrl: string;
  file: string;
  createdAt: number;
  durationSeconds?: number;
  kind?: "baseline" | "emotion";
  emotion?: VoiceDesignEmotion | null;
  referenceCandidateId?: string | null;
  speechRate?: number;
  textCfg?: number;
  voiceCfg?: number;
  captionCfg?: number;
};

export type VoiceDesignEmotion = "normal" | "joy" | "anger" | "sorrow" | "delight";

export type StudioSettings = {
  speechRate: number;
  steps: number;
  textCfg: number;
  voiceCfg: number;
  captionCfg?: number;
  seed: number;
  quality: QualityPreset;
  lineGap?: number;
  llmBaseUrl: string;
  llmModel: string;
  emojiExpressions?: boolean;
  fillerRichness?: boolean;
};

export type ScriptCastContext = {
  role: string;
  /** A script-local, reader-facing character introduction. */
  description?: string;
  /** Legacy reader-facing introduction written by earlier SCENA versions. */
  setting?: string;
};
type GeneratedStudioProject = components["schemas"]["StudioProjectModel"];
export type StudioProject = {
  version: GeneratedStudioProject["version"];
  revision: number;
  id: GeneratedStudioProject["id"];
  title: GeneratedStudioProject["title"];
  characters: Character[];
  candidates: VoiceCandidate[];
  scenes: Scene[];
  settings: StudioSettings;
  ttsSelection?: TtsProjectSelection;
  /** Script-local role and reader-facing introduction; never overwrites the cast library. */
  scriptCastContexts?: Record<string, ScriptCastContext>;
};
