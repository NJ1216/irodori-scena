import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, value),
  };
}

describe("modelRegistryCache", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", memoryStorage());
    vi.resetModules();
  });

  afterEach(() => vi.unstubAllGlobals());

  it("restores display data after a module reload without persisting local paths", async () => {
    const first = await import("./modelRegistryCache");
    const registry = {
      version: 1,
      defaultCardId: "card",
      endpoints: [],
      cards: [{ id: "card", modelId: "gemma", localMetadata: { path: "C:/private/model.gguf", modelContextLimit: 32768 } }],
    } as never;
    first.modelRegistryCache.setLlm(registry);

    vi.resetModules();
    const restored = await import("./modelRegistryCache");
    expect(restored.modelRegistryCache.llm()?.cards[0]?.modelId).toBe("gemma");
    expect(JSON.stringify(restored.modelRegistryCache.llm())).not.toContain("C:/private");
  });

  it("discards malformed persisted data", async () => {
    localStorage.setItem("scena-model-registry-cache-v1", "{");
    const restored = await import("./modelRegistryCache");
    expect(restored.modelRegistryCache.llm()).toBeNull();
    expect(localStorage.getItem("scena-model-registry-cache-v1")).toBeNull();
  });

  it("uses restored TTS data for presentation without treating it as session-fresh", async () => {
    const first = await import("./modelRegistryCache");
    first.modelRegistryCache.setTts({
      version: 1,
      defaultEngineId: null,
      defaultModelId: null,
      engines: [],
      models: [],
      libraries: [],
      projectSelection: null,
    });
    expect(first.modelRegistryCache.ttsIsFresh()).toBe(true);

    vi.resetModules();
    const restored = await import("./modelRegistryCache");
    expect(restored.modelRegistryCache.tts()).not.toBeNull();
    expect(restored.modelRegistryCache.ttsIsFresh()).toBe(false);
  });
});
