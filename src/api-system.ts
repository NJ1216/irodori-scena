import type { PronunciationDictionaryEntry, StudioProject } from "./types";
import { request } from "./api-core";
export const systemApi = {
  health: () => request<{ ok: boolean; apiSchemaHash?: string }>("/api/health"),
  historyStatus: (scope: "script" | "characters" | "pronunciation") => request<{ scope: string; canUndo: boolean; canRedo: boolean; busy: boolean }>(`/api/history/${scope}`),
  changeHistory: (scope: "script" | "characters" | "pronunciation", direction: "undo" | "redo") => request<{ scope: string; canUndo: boolean; canRedo: boolean; busy: boolean }>(`/api/history/${scope}/${direction}`, { method: "POST" }),
  project: () => request<StudioProject>(`/api/project?refresh=${Date.now()}`),
  pronunciationDictionary: (suggestReadings = true) => request<PronunciationDictionaryEntry[]>(`/api/pronunciation-dictionary?suggest_readings=${suggestReadings}`),
  changePronunciationDictionary: (change: import("./types").PronunciationDictionaryChange) =>
    request<import("./types").PronunciationDictionaryChangeResult>("/api/pronunciation-dictionary/change", {
      method: "POST",
      body: JSON.stringify(change),
    }),
  suggestCastPronunciations: () => request<PronunciationDictionaryEntry[]>("/api/pronunciation-dictionary/cast-suggest", { method: "POST" }),
  addCastPronunciationEntry: (characterId: string, term: string, reading: string) =>
    request<PronunciationDictionaryEntry>("/api/pronunciation-dictionary/cast", {
      method: "POST",
      body: JSON.stringify({ character_id: characterId, term, reading }),
    }),
  deleteCastPronunciationEntry: (id: string) => request<{ ok: boolean }>(`/api/pronunciation-dictionary/cast/${id}`, { method: "DELETE" }),
  suggestManualPronunciations: () => request<PronunciationDictionaryEntry[]>("/api/pronunciation-dictionary/suggest", { method: "POST" }),
  addPronunciationEntry: (term: string, reading: string) =>
    request<PronunciationDictionaryEntry>("/api/pronunciation-dictionary", {
      method: "POST",
      body: JSON.stringify({ term, reading }),
    }),
  updatePronunciationEntry: (id: string, term: string, reading: string) =>
    request<PronunciationDictionaryEntry>(`/api/pronunciation-dictionary/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ term, reading }),
    }),
  updateCastPronunciationReading: (id: string, reading: string) =>
    request<PronunciationDictionaryEntry>(`/api/pronunciation-dictionary/${id}/reading`, {
      method: "PATCH",
      body: JSON.stringify({ reading }),
    }),
  setPronunciationLock: (id: string, locked: boolean) =>
    request<PronunciationDictionaryEntry>(`/api/pronunciation-dictionary/${id}/lock`, {
      method: "PATCH",
      body: JSON.stringify({ locked }),
    }),
  deletePronunciationEntry: (id: string) => request<{ ok: boolean }>(`/api/pronunciation-dictionary/${id}`, { method: "DELETE" }),
  engineSettings: () => request<{ engineDir: string; engineDirVerified: boolean }>("/api/settings/engine-directory"),
  ttsCatalog: () => request<import("./types").TtsCatalog>("/api/tts/catalog"),
  ttsRegistry: () => request<import("./types").TtsRegistry>("/api/tts/registry"),
  ttsRuntimeStatus: () => request<import("./types").TtsRuntimeStatus>("/api/tts/runtime/status"),
  prepareTtsRuntime: () => request<import("./types").TtsRuntimeStatus>("/api/tts/runtime/prepare", { method: "POST" }),
  setTtsDefaults: (modelId: string, engineId?: string | null) =>
    request<import("./types").TtsRegistry>("/api/tts/defaults", {
      method: "PUT",
      body: JSON.stringify({ engine_id: engineId ?? null, model_id: modelId }),
    }),
  setProjectTtsSelection: (modelId: string, engineId?: string | null) =>
    request<import("./types").TtsProjectSelection>("/api/project/tts-selection", {
      method: "PUT",
      body: JSON.stringify({ engine_id: engineId ?? null, model_id: modelId }),
    }),
  setTtsActiveVariant: (modelId: string, variantId: string) =>
    request<import("./types").TtsRegistry>(`/api/tts/models/${encodeURIComponent(modelId)}/active-variant`, {
      method: "PUT",
      body: JSON.stringify({ variant_id: variantId }),
    }),
  startTtsVariantInstall: (modelId: string, variantId: string) => request<import("./types").TtsInstallJob>(`/api/tts/models/${encodeURIComponent(modelId)}/variants/${encodeURIComponent(variantId)}/downloads`, { method: "POST" }),
  deleteTtsVariant: (modelId: string, variantId: string) => request<import("./types").TtsRegistry>(`/api/tts/models/${encodeURIComponent(modelId)}/variants/${encodeURIComponent(variantId)}`, { method: "DELETE" }),
  registerExternalTtsEngine: (path: string) =>
    request<import("./types").TtsRegistry>("/api/tts/external-engines", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  scanTtsLibrary: (path: string) =>
    request<import("./types").TtsLibraryScan>("/api/tts/libraries/scan", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  registerTtsLibrary: (root: string, enginePath: string, displayName?: string) =>
    request<import("./types").TtsRegistry>("/api/tts/libraries", {
      method: "POST",
      body: JSON.stringify({ root, engine_path: enginePath, display_name: displayName }),
    }),
  disconnectTtsLibrary: (id: string) => request<import("./types").TtsRegistry>(`/api/tts/libraries/${encodeURIComponent(id)}`, { method: "DELETE" }),
  registerTtsLibraryModel: (libraryId: string, modelPath: string, codecPath: string) =>
    request<import("./types").TtsLibraryModelJob>(`/api/tts/libraries/${encodeURIComponent(libraryId)}/models`, {
      method: "POST",
      body: JSON.stringify({ model_path: modelPath, codec_path: codecPath }),
    }),
  ttsLibraryModelJob: (id: string) => request<import("./types").TtsLibraryModelJob>(`/api/tts/library-model-jobs/${encodeURIComponent(id)}`),
  cancelTtsLibraryModelJob: (id: string) =>
    request<import("./types").TtsLibraryModelJob>(`/api/tts/library-model-jobs/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
    }),
  startTtsInstall: (kind: "engine" | "model", id: string) =>
    request<import("./types").TtsInstallJob>(`/api/tts/${kind}/${encodeURIComponent(id)}/downloads`, {
      method: "POST",
    }),
  ttsInstall: (id: string) => request<import("./types").TtsInstallJob>(`/api/tts/downloads/${encodeURIComponent(id)}`),
  cancelTtsInstall: (id: string) => request<import("./types").TtsInstallJob>(`/api/tts/downloads/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  verifyTtsAsset: (kind: "engine" | "model", id: string) => request<{ valid: boolean; card: import("./types").TtsAssetCard }>(`/api/tts/${kind}/${encodeURIComponent(id)}/verify`, { method: "POST" }),
  deleteTtsAsset: (kind: "engine" | "model", id: string) => request<import("./types").TtsRegistry>(`/api/tts/${kind}/${encodeURIComponent(id)}`, { method: "DELETE" }),
  memorySnapshot: () => request<import("./types").MemorySnapshot>("/api/system/memory"),
};
