import type { LlmRegistry, TtsCatalog, TtsRegistry } from "../../types";

let llmRegistry: LlmRegistry | null = null;
let ttsRegistry: TtsRegistry | null = null;
let ttsCatalog: TtsCatalog | null = null;
let ttsRegistryFresh = false;
const STORAGE_KEY = "scena-model-registry-cache-v1";

type CacheEnvelope = {
  schemaVersion: 1;
  savedAt: string;
  llm: LlmRegistry | null;
  tts: TtsRegistry | null;
  catalog: TtsCatalog | null;
};

function restore() {
  try {
    const value = JSON.parse(globalThis.localStorage?.getItem(STORAGE_KEY) ?? "null") as CacheEnvelope | null;
    if (value?.schemaVersion !== 1) return;
    llmRegistry = value.llm;
    ttsRegistry = value.tts;
    ttsCatalog = value.catalog;
  } catch {
    globalThis.localStorage?.removeItem(STORAGE_KEY);
  }
}

function persist() {
  try {
    const presentationCopy = <T>(value: T): T =>
      JSON.parse(
        JSON.stringify(value, (key, item) => {
          const normalized = key.toLowerCase();
          return normalized === "path" || normalized === "files" || normalized.includes("credential") || normalized === "apikey" ? undefined : item;
        }),
      ) as T;
    const value: CacheEnvelope = {
      schemaVersion: 1,
      savedAt: new Date().toISOString(),
      llm: presentationCopy(llmRegistry),
      tts: presentationCopy(ttsRegistry),
      catalog: presentationCopy(ttsCatalog),
    };
    globalThis.localStorage?.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // A presentation cache must never block authoritative API loading.
  }
}

restore();

export const modelRegistryCache = {
  llm: () => llmRegistry,
  tts: () => ttsRegistry,
  ttsIsFresh: () => ttsRegistryFresh,
  catalog: () => ttsCatalog,
  setLlm: (value: LlmRegistry) => {
    llmRegistry = value;
    persist();
  },
  setTts: (value: TtsRegistry) => {
    ttsRegistry = value;
    ttsRegistryFresh = true;
    persist();
  },
  setCatalog: (value: TtsCatalog) => {
    ttsCatalog = value;
    persist();
  },
  reset: () => {
    llmRegistry = null;
    ttsRegistry = null;
    ttsCatalog = null;
    ttsRegistryFresh = false;
    globalThis.localStorage?.removeItem(STORAGE_KEY);
  },
};
