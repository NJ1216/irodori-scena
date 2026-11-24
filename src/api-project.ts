import type {
  Character,
  CharacterProfile,
  ImagePromptPreferences,
  ImagePromptSuggestionRequest,
  ProfileSuggestionRequest,
  DraftJob,
  LlmSessionUsage,
  ExportJob,
  LineGenerationResult,
  ProgressEvent,
  ProfileSuggestionResult,
  ProfileSuggestionJob,
  ProjectBackupResult,
  ProjectOptimizationResult,
  RhubarbInstallJob,
  RhubarbStatus,
  StudioProject,
  VoiceCandidate,
  VoiceDesignEmotion,
  WorkspaceResult,
} from "./types";
import type { VoiceDesign } from "./features/characters/voiceDesign";
import type { ScriptAssistantJob } from "./features/script/scriptAssistantTypes";
import { streamApiEvents } from "./api-runtime";
import { readFileAsBase64, request } from "./api-core";
type ScriptAssistantApplyPayload = {
  source_signature: string;
  accepted_row_ids: string[];
  accepted_group_ids: string[];
};
export const projectApi = {
  exportCasts: (castIds: string[], destinationDir: string, overwrite = false) =>
    request<{ destinationDir: string; warnings?: string[]; results: Array<{ castId: string; name?: string; status: "exported" | "failed"; path?: string; error?: string }> }>("/api/casts/export", {
      method: "POST",
      body: JSON.stringify({ cast_ids: castIds, destination_dir: destinationDir, overwrite }),
    }),
  prepareCastImport: (paths: string[]) => request<import("./types").CastImportPreparation>("/api/casts/import/prepare", { method: "POST", body: JSON.stringify({ paths }) }),
  commitCastImport: (sessionId: string, decisions: Array<{ incomingKey: string; action: "overwrite" | "skip" }>) =>
    request<{ applied: Array<{ key: string; castId: string; status: string }>; skipped: Array<{ key: string; status: string }>; project: StudioProject }>("/api/casts/import/commit", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, decisions: decisions.map((item) => ({ incoming_key: item.incomingKey, action: item.action })) }),
    }),
  cancelCastImport: (sessionId: string) => request<{ cancelled: boolean }>("/api/casts/import/cancel", { method: "POST", body: JSON.stringify({ session_id: sessionId }) }),
  chooseEngineDirectory: (directory?: string) =>
    request<{ engineDir: string }>("/api/settings/engine-directory", {
      method: "POST",
      body: directory ? JSON.stringify({ path: directory }) : undefined,
    }),
  saveProject: (project: StudioProject) =>
    request<StudioProject>("/api/project", {
      method: "PUT",
      body: JSON.stringify({ project, baseRevision: project.revision }),
    }),
  patchProjectMetadata: (baseRevision: number, changes: Partial<Pick<StudioProject, "title">>) =>
    request<{ revision: number }>("/api/project/metadata", {
      method: "PATCH",
      body: JSON.stringify({ baseRevision, changes }),
    }),
  patchProjectSettings: (baseRevision: number, changes: Partial<StudioProject["settings"]>) =>
    request<{ revision: number }>("/api/project/settings", {
      method: "PATCH",
      body: JSON.stringify({ baseRevision, changes }),
    }),
  patchProjectLine: (lineId: string, baseRevision: number, changes: Partial<import("./types").DialogueLine>) =>
    request<{ revision: number }>(`/api/lines/${encodeURIComponent(lineId)}`, {
      method: "PATCH",
      body: JSON.stringify({ baseRevision, changes }),
    }),
  reorderCharacters: (baseRevision: number, characterIds: string[]) =>
    request<StudioProject>("/api/characters/order", {
      method: "PATCH",
      body: JSON.stringify({ baseRevision, characterIds }),
    }),
  backupWorkspace: (path: string) =>
    request<ProjectBackupResult>("/api/project/backup", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  optimizeWorkspace: () => request<ProjectOptimizationResult>("/api/project/optimize", { method: "POST" }),
  optimizationStatus: () => request<{ available: boolean }>("/api/project/optimization-status"),
  importScript: (lines: Array<{ character_id: string; text: string }>) =>
    request<StudioProject>("/api/project/import-script", {
      method: "POST",
      body: JSON.stringify({ lines }),
    }),
  saveWorkspace: (directory?: string) =>
    request<WorkspaceResult>("/api/project/save-workspace", {
      method: "POST",
      body: directory ? JSON.stringify({ path: directory }) : undefined,
    }),
  workspace: () => request<WorkspaceResult["workspace"]>("/api/project/workspace"),
  openWorkspace: (directory?: string) =>
    request<WorkspaceResult>("/api/project/open-workspace", {
      method: "POST",
      body: directory ? JSON.stringify({ path: directory }) : undefined,
    }),
  applyGlobalCastUpdates: (characterIds: string[]) =>
    request<StudioProject>("/api/project/apply-global-cast-updates", {
      method: "POST",
      body: JSON.stringify({ character_ids: characterIds }),
    }),
  candidates: (
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
  ) =>
    request<{ candidates: VoiceCandidate[] }>("/api/characters/candidates", {
      method: "POST",
      body: JSON.stringify({
        keywords,
        count,
        sample_text: sampleText,
        kind: options?.kind ?? "baseline",
        emotion: options?.emotion,
        reference_candidate_id: options?.referenceCandidateId,
        speech_rate: options?.speechRate,
        text_cfg: options?.textCfg,
        voice_cfg: options?.voiceCfg,
        caption_cfg: options?.captionCfg,
        voice_design: options?.voiceDesign,
      }),
    }),
  clearCandidates: () =>
    request<StudioProject>("/api/characters/candidates/clear", {
      method: "POST",
    }),
  clearCandidateScope: (kind: "baseline" | "emotion", options?: { emotion?: VoiceDesignEmotion; referenceCandidateId?: string }) =>
    request<StudioProject>(`/api/characters/candidates/clear-scope?${new URLSearchParams({ kind, ...(options?.emotion ? { emotion: options.emotion } : {}), ...(options?.referenceCandidateId ? { reference_candidate_id: options.referenceCandidateId } : {}) })}`, { method: "POST" }),
  importVoiceDesignReference: async (file: File, options?: { kind: "baseline" | "emotion"; emotion?: VoiceDesignEmotion; referenceCandidateId?: string }) =>
    request<{ candidate: VoiceCandidate }>("/api/characters/candidates/import-reference", {
      method: "POST",
      body: JSON.stringify({
        audio_base64: await readFileAsBase64(file),
        kind: options?.kind ?? "baseline",
        emotion: options?.emotion,
        reference_candidate_id: options?.referenceCandidateId,
      }),
    }),
  acceptCandidate: (candidateId: string, name: string, profile: string) =>
    request<Character>("/api/characters/accept", {
      method: "POST",
      body: JSON.stringify({ candidate_id: candidateId, name, profile }),
    }),
  importReference: async (file: File, name: string, profile: string) =>
    request<Character>("/api/characters/import", {
      method: "POST",
      body: JSON.stringify({
        name,
        profile,
        audio_base64: await readFileAsBase64(file),
      }),
    }),
  updateReference: async (characterId: string, file: File) =>
    request<{ character: Character; project: StudioProject; invalidatedLines: number }>(`/api/characters/${characterId}/reference`, {
      method: "PUT",
      body: JSON.stringify({ audio_base64: await readFileAsBase64(file) }),
    }),
  applyCandidateReference: (characterId: string, candidateId: string) =>
    request<{ character: Character; project: StudioProject; invalidatedLines: number }>(`/api/characters/${characterId}/reference/candidate`, {
      method: "POST",
      body: JSON.stringify({ candidate_id: candidateId }),
    }),
  saveVoiceDesign: (payload: { baselineCandidateId: string; emotionCandidateIds: Partial<Record<VoiceDesignEmotion, string>>; name: string; profile: string; voiceKeywords: string; voiceDesign: VoiceDesign; characterId?: string }) =>
    request<{ character: Character; project: StudioProject; invalidatedLines: number }>("/api/characters/voice-design/save", {
      method: "POST",
      body: JSON.stringify({
        baseline_candidate_id: payload.baselineCandidateId,
        emotion_candidate_ids: payload.emotionCandidateIds,
        name: payload.name,
        profile: payload.profile,
        voice_keywords: payload.voiceKeywords,
        voice_design: payload.voiceDesign,
        character_id: payload.characterId,
      }),
    }),
  updateCharacter: (
    characterId: string,
    name: string,
    profile: string,
    voiceKeywords: string,
    profileDetails: CharacterProfile,
    imagePrompt: string | undefined,
    imagePromptPreferences: ImagePromptPreferences | undefined,
    lora?: import("./types/project").LoraReference | null,
    loraMix?: import("./types/project").LoraMix | null,
  ) =>
    request<Character>(`/api/characters/${characterId}`, {
      method: "PATCH",
      body: JSON.stringify({
        name,
        profile,
        voice_keywords: voiceKeywords,
        profile_details: profileDetails,
        image_prompt: imagePrompt,
        image_prompt_preferences: imagePromptPreferences,
        ...(lora !== undefined ? { lora } : {}),
        ...(loraMix !== undefined ? { loraMix } : {}),
      }),
    }),
  updateCharacterAvatar: (characterId: string, originalImageBase64: string, thumbnailImageBase64: string) =>
    request<Character>(`/api/characters/${characterId}/avatar`, {
      method: "PUT",
      body: JSON.stringify({
        original_image_base64: originalImageBase64,
        thumbnail_image_base64: thumbnailImageBase64,
      }),
    }),
  deleteCharacterAvatar: (characterId: string) =>
    request<Character>(`/api/characters/${characterId}/avatar`, {
      method: "DELETE",
    }),
  deleteCharacter: (characterId: string) =>
    request<StudioProject>(`/api/characters/${characterId}`, {
      method: "DELETE",
    }),
  suggestTheme: (payload: {
    theme: string;
    target_minutes: number;
    character_ids: string[];
    cast_settings: Record<
      string,
      {
        emoji_expressions: boolean;
        filler_richness: boolean;
        appearance_priority: "main" | "supporting" | "standard";
      }
    >;
  }) =>
    request<{ theme: string }>("/api/drafts/theme-suggestion", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  suggestVoiceDesign: (payload: { keywords: string; character_context?: string }) =>
    request<{
      voiceDesign?: Partial<VoiceDesign> | null;
      baselineText?: string | null;
      emotionTexts: Partial<Record<VoiceDesignEmotion, string>>;
    }>("/api/characters/voice-design-suggestion", { method: "POST", body: JSON.stringify(payload) }),
  suggestCharacterProfile: (payload: ProfileSuggestionRequest) =>
    request<ProfileSuggestionResult>("/api/characters/profile-suggestion", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  startCharacterProfileSuggestion: (payload: ProfileSuggestionRequest) =>
    request<ProfileSuggestionJob>("/api/characters/profile-suggestion/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  characterProfileSuggestionJob: (jobId: string) => request<ProfileSuggestionJob>(`/api/characters/profile-suggestion/jobs/${jobId}`),
  cancelCharacterProfileSuggestion: (jobId: string) => request<ProfileSuggestionJob>(`/api/characters/profile-suggestion/jobs/${jobId}/cancel`, { method: "POST" }),
  characterProfileSuggestionEvents: (jobId: string, onEvent: (event: ProgressEvent) => void, options?: { signal?: AbortSignal; lastEventId?: number }) => streamApiEvents(`/api/characters/profile-suggestion/jobs/${jobId}/events`, onEvent, options),
  suggestCharacterImagePrompt: (payload: ImagePromptSuggestionRequest) =>
    request<{ imagePrompt: string; usedLlm?: boolean; ignoredCustomFields?: string[]; warnings?: string[] }>("/api/characters/image-prompt-suggestion", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  generateLine: (lineId: string, quality: "turbo" | "fast" | "quality", interruptible = false, seed?: number, historyBaseRevision?: number, historyGroupId?: string) =>
    request<LineGenerationResult>(`/api/lines/${lineId}/generate`, {
      method: "POST",
      headers: { ...(historyBaseRevision !== undefined ? { "X-SCENA-History-Base-Revision": String(historyBaseRevision) } : {}), ...(historyGroupId ? { "X-SCENA-History-Group": historyGroupId } : {}) },
      body: JSON.stringify({ quality, interruptible, seed }),
    }),
  regenerateLine: (lineId: string, quality: "turbo" | "fast" | "quality", interruptible = false, targetTakeId?: string, historyBaseRevision?: number, historyGroupId?: string) =>
    request<LineGenerationResult>(`/api/lines/${lineId}/regenerate`, {
      method: "POST",
      headers: { ...(historyBaseRevision !== undefined ? { "X-SCENA-History-Base-Revision": String(historyBaseRevision) } : {}), ...(historyGroupId ? { "X-SCENA-History-Group": historyGroupId } : {}) },
      body: JSON.stringify({ quality, interruptible, targetTakeId }),
    }),
  cancelAutoRender: (lineId?: string) => request<{ cancelled: boolean }>("/api/lines/auto-render/cancel", { method: "POST", ...(lineId ? { body: JSON.stringify({ lineId }) } : {}) }),
  deleteTake: (lineId: string, takeId: string) =>
    request<StudioProject>(`/api/lines/${lineId}/takes/${takeId}`, {
      method: "DELETE",
    }),
  cleanupLineTakes: (lineIds: string[], mode: "unselected" | "all") => request<StudioProject>("/api/lines/cleanup-takes", { method: "POST", body: JSON.stringify({ line_ids: lineIds, mode }) }),
  changeLineCharacter: (lineId: string, characterId: string) =>
    request<StudioProject>(`/api/lines/${lineId}/character`, {
      method: "PATCH",
      body: JSON.stringify({ character_id: characterId }),
    }),
  switchCharacters: (mappings: Array<{ fromCharacterId: string; toCharacterId: string }>) =>
    request<{ project: StudioProject; invalidatedLines: number }>("/api/project/switch-characters", {
      method: "POST",
      body: JSON.stringify({
        mappings: mappings.map((mapping) => ({
          from_character_id: mapping.fromCharacterId,
          to_character_id: mapping.toCharacterId,
        })),
      }),
    }),
  deleteLine: (sceneId: string, lineId: string) => request<StudioProject>(`/api/scenes/${sceneId}/lines/${lineId}`, { method: "DELETE" }),
  deleteLines: (lineIds: string[]) => request<StudioProject>("/api/lines/batch-delete", { method: "POST", body: JSON.stringify({ line_ids: lineIds }) }),
  deleteScene: (sceneId: string) => request<StudioProject>(`/api/scenes/${sceneId}`, { method: "DELETE" }),
  insertLine: (sceneId: string, beforeLineId?: string) =>
    request<StudioProject>(`/api/scenes/${sceneId}/lines`, {
      method: "POST",
      body: JSON.stringify({ before_line_id: beforeLineId ?? "" }),
    }),
  splitLine: (sceneId: string, lineId: string, offset: number) =>
    request<StudioProject>(`/api/scenes/${sceneId}/lines`, {
      method: "POST",
      body: JSON.stringify({ split_line_id: lineId, split_offset: offset }),
    }),
  addCueMember: (sceneId: string, lineId: string, characterId: string) =>
    request<StudioProject>(`/api/scenes/${sceneId}/lines/${lineId}/cue-members`, {
      method: "POST",
      body: JSON.stringify({ character_id: characterId }),
    }),
  mixCue: (sceneId: string, lineId: string) => request<{ audioUrl: string; durationSeconds: number; cueId: string; signature: string }>(`/api/scenes/${sceneId}/lines/${lineId}/cue-mix`, { method: "POST" }),
  mixOverlap: (leadingLineId: string, signal?: AbortSignal) =>
    request<{
      audioUrl: string;
      durationSeconds: number;
      preRollSeconds: number;
      postRollSeconds: number;
      followingGain: number;
      effectiveGapSeconds: number;
      signature: string;
      leadingLineIds: string[];
      followingLineIds: string[];
      diagnostics: {
        snapshotMs: number;
        queueWaitMs: number;
        hashMs: number;
        cacheHit: boolean;
        cacheLookupMs: number;
        nativeMs: number;
      };
    }>(`/api/lines/${leadingLineId}/overlap-mix`, { method: "POST", signal }),
  prepareDerivedAudio: () => request<{ projectKey: string; boundaries: string[] }>("/api/project/timeline/background", { method: "POST" }),
  prioritizeDerivedAudio: (leadingLineIds: string[]) =>
    request<{ projectKey: string; boundaries: Array<{ leadingLineId: string; status: string }> }>("/api/project/derived-audio/prioritize", {
      method: "POST",
      body: JSON.stringify({ leading_line_ids: leadingLineIds.slice(0, 2) }),
    }),
  derivedAudioStatus: () => request<{ projectKey: string; boundaries: Array<{ leadingLineId: string; status: string }> }>("/api/project/derived-audio/status"),
  startPlaybackPreparation: (playbackId: string, boundaries: Array<{ leadingLineId: string; deadlineInMs: number }>) =>
    request("/api/project/playback/start", {
      method: "POST",
      body: JSON.stringify({
        playback_id: playbackId,
        boundaries: boundaries.slice(0, 2).map((boundary) => ({ leading_line_id: boundary.leadingLineId, deadline_in_ms: boundary.deadlineInMs })),
      }),
    }),
  updatePlaybackPreparation: (playbackId: string, boundaries: Array<{ leadingLineId: string; deadlineInMs: number }>) =>
    request("/api/project/playback/update", {
      method: "POST",
      body: JSON.stringify({
        playback_id: playbackId,
        boundaries: boundaries.slice(0, 2).map((boundary) => ({ leading_line_id: boundary.leadingLineId, deadline_in_ms: boundary.deadlineInMs })),
      }),
    }),
  stopPlaybackPreparation: (playbackId: string) => request(`/api/project/playback/${encodeURIComponent(playbackId)}/stop`, { method: "POST" }),
  clearAllTakes: () => request<StudioProject>("/api/project/clear-takes", { method: "POST" }),
  createNewProject: () => request<WorkspaceResult>("/api/project/new", { method: "POST" }),
  notifyInferenceInteraction: () => request<{ ok: boolean }>("/api/inference/interaction-lease", { method: "POST" }),
  suggestLineInsert: (payload: Record<string, unknown>) =>
    request<{ instruction: string }>("/api/lines/assistant/suggest", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  generateLineInsert: (payload: Record<string, unknown>) =>
    request<StudioProject>("/api/lines/assistant/generate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  suggestScriptAssistant: (payload: Record<string, unknown>) =>
    request<{ instruction: string }>("/api/lines/assistant/suggest-v2", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  startScriptAssistantJob: (payload: Record<string, unknown>) => request<ScriptAssistantJob>("/api/lines/assistant/jobs", { method: "POST", body: JSON.stringify(payload) }),
  scriptAssistantJob: (jobId: string) => request<ScriptAssistantJob>(`/api/lines/assistant/jobs/${encodeURIComponent(jobId)}`),
  cancelScriptAssistantJob: (jobId: string) => request<ScriptAssistantJob>(`/api/lines/assistant/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }),
  applyScriptAssistantProposal: (proposalId: string, payload: ScriptAssistantApplyPayload) =>
    request<StudioProject>(`/api/lines/assistant/proposals/${encodeURIComponent(proposalId)}/apply`, {
      method: "POST",
      body: JSON.stringify({ proposal_id: proposalId, ...payload }),
    }),
  startAiJob: (payload: Record<string, unknown>) =>
    request<DraftJob>("/api/ai/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  aiJob: (jobId: string) => request<DraftJob>(`/api/ai/jobs/${jobId}`),
  aiJobEvents: (jobId: string, onEvent: (event: ProgressEvent) => void, options?: { signal?: AbortSignal; lastEventId?: number }) => streamApiEvents(`/api/ai/jobs/${jobId}/events`, onEvent, options),
  cancelAiJob: (jobId: string) => request<DraftJob>(`/api/ai/jobs/${jobId}/cancel`, { method: "POST" }),
  llmSessionUsage: () => request<LlmSessionUsage>("/api/llm/session-usage"),
  resetLlmSessionUsage: () => request<LlmSessionUsage>("/api/llm/session-usage/reset", { method: "POST" }),
  startExportJob: () =>
    request<ExportJob>("/api/exports/jobs", {
      method: "POST",
      body: JSON.stringify({ mode: "prepare" }),
    }),
  startExportBundle: (settings: { destinationDir: string; layout: "split" | "joined"; formats: Array<"wav" | "subtitle_txt" | "script_txt" | "srt" | "lab">; naming: Array<"sequence" | "cast" | "text" | "none">; scriptDelimiter: string; quoteDialogue: boolean; subtitleIncludeEmoji: boolean }) =>
    request<ExportJob>("/api/exports/jobs", { method: "POST", body: JSON.stringify({ mode: "bundle", ...settings }) }),
  exportJob: (jobId: string, afterUpdate = 0) => request<ExportJob>(`/api/exports/jobs/${jobId}?after_update=${afterUpdate}`),
  exportJobEvents: (jobId: string, onEvent: (event: ProgressEvent) => void, options?: { signal?: AbortSignal; lastEventId?: number }) => streamApiEvents(`/api/exports/jobs/${jobId}/events`, onEvent, options),
  cancelExportJob: (jobId: string) => request<ExportJob>(`/api/exports/jobs/${jobId}/cancel`, { method: "POST" }),
  cancelActiveExportJob: () => request<ExportJob>("/api/exports/jobs/cancel-active", { method: "POST" }),
  rhubarbStatus: () => request<RhubarbStatus>("/api/lipsync/rhubarb"),
  installRhubarb: () => request<RhubarbInstallJob>("/api/lipsync/rhubarb/install", { method: "POST" }),
  cancelRhubarbInstall: () => request<RhubarbInstallJob>("/api/lipsync/rhubarb/install/cancel", { method: "POST" }),
  deleteRhubarb: () => request<RhubarbStatus>("/api/lipsync/rhubarb", { method: "DELETE" }),
};
