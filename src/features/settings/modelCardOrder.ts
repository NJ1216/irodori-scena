import type { LlmCard, LlmEndpoint, TtsAssetCard } from "../../types";

const ttsRepoOrder = ["Aratako/Irodori-TTS-v4.1-Small", "Aratako/Irodori-TTS-v4-Large", "Aratako/Irodori-TTS-v4.1-Small-MF", "phasefield-audio/Irodori-TTS-v4.1-Anime", "Aratako/Irodori-TTS-v4-Small", "Aratako/Irodori-TTS-500M-v3", "Aratako/Irodori-TTS-600M-v3-VoiceDesign"];

export function sortTtsModelCards(cards: TtsAssetCard[]) {
  const rank = new Map(ttsRepoOrder.map((repo, index) => [repo, index]));
  return [...cards].sort((a, b) => (rank.get(a.repo ?? "") ?? Number.MAX_SAFE_INTEGER) - (rank.get(b.repo ?? "") ?? Number.MAX_SAFE_INTEGER));
}

const llmProviderOrder: Record<LlmEndpoint["provider"], number> = {
  "scena-local": 0,
  ollama: 1,
  lmstudio: 2,
  openai: 3,
};

export function sortLlmModelCards(cards: LlmCard[], endpoints: LlmEndpoint[]) {
  const providers = new Map(endpoints.map((endpoint) => [endpoint.id, endpoint.provider]));
  return [...cards].sort((a, b) => {
    const aProvider = providers.get(a.endpointId);
    const bProvider = providers.get(b.endpointId);
    return (aProvider ? llmProviderOrder[aProvider] : Number.MAX_SAFE_INTEGER) - (bProvider ? llmProviderOrder[bProvider] : Number.MAX_SAFE_INTEGER);
  });
}
