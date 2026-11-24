import { useEffect, useState } from "react";
import { api } from "../../api";
import type { StudioProject, TtsRegistry } from "../../types";
import { modelRegistryCache } from "../shared/modelRegistryCache";

type SelectedCapabilities = TtsRegistry["selectedModelCapabilities"];

function cachedCapabilities(): SelectedCapabilities | undefined {
  if (!modelRegistryCache.ttsIsFresh()) return undefined;
  return modelRegistryCache.tts()?.selectedModelCapabilities;
}

export function useTtsCapabilityReasons(_selection: StudioProject["ttsSelection"]) {
  const cached = cachedCapabilities();
  const [loaded, setLoaded] = useState<SelectedCapabilities>(cached ?? null);
  const capabilities = cached !== undefined ? cached : loaded;
  useEffect(() => {
    if (cachedCapabilities() !== undefined) return;
    let active = true;
    void api
      .ttsRegistry()
      .then((value) => {
        modelRegistryCache.setTts(value);
        if (active) setLoaded(value.selectedModelCapabilities);
      })
      .catch(() => {
        if (active) setLoaded(null);
      });
    return () => {
      active = false;
    };
  }, []);
  return {
    voiceDesignUnavailableReason: capabilities && !capabilities.voiceDesign ? "選択中の音声モデルはVoiceDesignに対応していません。" : "",
    combinedVoiceDesignUnavailableReason: capabilities && !capabilities.combinedReferenceCaption ? "選択中の音声モデルは参照音声とVoiceDesignの併用に対応していません。" : "",
  };
}
