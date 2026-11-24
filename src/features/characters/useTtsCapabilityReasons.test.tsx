import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import type { TtsProjectSelection, TtsRegistry } from "../../types";
import { modelRegistryCache } from "../shared/modelRegistryCache";
import { useTtsCapabilityReasons } from "./useTtsCapabilityReasons";

const selection: TtsProjectSelection = {
  engine: { repo: "engine", commit: "commit", externalId: null },
  model: { repo: "model", revision: "revision" },
  codecRevision: "codec",
  optimizationProfile: "compatible",
};

const registry = (voiceDesign: boolean, projectSelection: TtsProjectSelection | null = selection): TtsRegistry =>
  ({
    version: 1,
    defaultEngineId: null,
    defaultModelId: null,
    engines: [],
    models: [],
    libraries: [],
    projectSelection,
    selectedModelCapabilities: { voiceDesign, combinedReferenceCaption: voiceDesign },
  }) satisfies TtsRegistry;

describe("useTtsCapabilityReasons", () => {
  beforeEach(() => {
    modelRegistryCache.reset();
    vi.restoreAllMocks();
  });

  it("uses cached device capabilities without another request", () => {
    modelRegistryCache.setTts(registry(false));
    const request = vi.spyOn(api, "ttsRegistry");
    const { result } = renderHook(() => useTtsCapabilityReasons(structuredClone(selection)));

    expect(result.current.voiceDesignUnavailableReason).not.toBe("");
    expect(request).not.toHaveBeenCalled();
  });

  it("requests and caches capabilities when the device registry cache is stale", async () => {
    modelRegistryCache.setTts(registry(false, null));
    modelRegistryCache.reset();
    const request = vi.spyOn(api, "ttsRegistry").mockResolvedValue(registry(true));
    const { result } = renderHook(() => useTtsCapabilityReasons(selection));

    await waitFor(() => expect(request).toHaveBeenCalledOnce());
    await waitFor(() => expect(result.current.voiceDesignUnavailableReason).toBe(""));
    expect(modelRegistryCache.tts()?.selectedModelCapabilities?.voiceDesign).toBe(true);
  });

  it("does not request again when an equivalent selection object is supplied", () => {
    modelRegistryCache.setTts(registry(true));
    const request = vi.spyOn(api, "ttsRegistry");
    const hook = renderHook(({ value }) => useTtsCapabilityReasons(value), { initialProps: { value: selection } });

    act(() => hook.rerender({ value: structuredClone(selection) }));
    expect(request).not.toHaveBeenCalled();
  });
});
