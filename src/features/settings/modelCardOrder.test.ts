import { expect, it } from "vitest";
import type { LlmCard, LlmEndpoint, TtsAssetCard } from "../../types";
import { sortLlmModelCards, sortTtsModelCards } from "./modelCardOrder";

it("orders TTS cards by the product model sequence", () => {
  const repos = ["Aratako/Irodori-TTS-600M-v3-VoiceDesign", "phasefield-audio/Irodori-TTS-v4.1-Anime", "Aratako/Irodori-TTS-v4.1-Small", "Aratako/Irodori-TTS-v4-Large", "Aratako/Irodori-TTS-500M-v3", "Aratako/Irodori-TTS-v4-Small", "Aratako/Irodori-TTS-v4.1-Small-MF"];
  const cards = repos.map((repo) => ({ repo }) as TtsAssetCard);
  expect(sortTtsModelCards(cards).map((card) => card.repo)).toEqual([
    "Aratako/Irodori-TTS-v4.1-Small",
    "Aratako/Irodori-TTS-v4-Large",
    "Aratako/Irodori-TTS-v4.1-Small-MF",
    "phasefield-audio/Irodori-TTS-v4.1-Anime",
    "Aratako/Irodori-TTS-v4-Small",
    "Aratako/Irodori-TTS-500M-v3",
    "Aratako/Irodori-TTS-600M-v3-VoiceDesign",
  ]);
});

it("orders LLM cards by built-in, Ollama, LM Studio, then external provider", () => {
  const endpoints = [
    { id: "external", provider: "openai" },
    { id: "lmstudio", provider: "lmstudio" },
    { id: "ollama", provider: "ollama" },
    { id: "built-in", provider: "scena-local" },
  ] as LlmEndpoint[];
  const cards = endpoints.map((endpoint) => ({ id: endpoint.id, endpointId: endpoint.id }) as LlmCard);
  expect(sortLlmModelCards(cards, endpoints).map((card) => card.id)).toEqual(["built-in", "ollama", "lmstudio", "external"]);
});
