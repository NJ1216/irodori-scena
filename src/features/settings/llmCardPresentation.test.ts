import { expect, it } from "vitest";
import { isAnthropicEndpoint, llmProviderLabel } from "./llmCardPresentation";

const endpoint = (baseUrl: string, provider: "openai" | "ollama" = "openai") => ({ id: "e", provider, displayName: "e", baseUrl, hasCredential: true });

it("labels only the official Anthropic endpoint as Anthropic", () => {
  for (const url of ["https://api.anthropic.com/v1", "https://api.anthropic.com/v1/", "https://api.anthropic.com"]) {
    expect(llmProviderLabel(endpoint(url))).toBe("Anthropic");
  }
  for (const url of ["http://api.anthropic.com/v1", "https://proxy.example/v1", "https://api.anthropic.com/v2", "not a url"]) {
    expect(isAnthropicEndpoint(endpoint(url))).toBe(false);
  }
  expect(llmProviderLabel(endpoint("https://api.openai.com/v1"))).toBe("OpenAI互換");
  expect(llmProviderLabel(endpoint("https://api.anthropic.com/v1", "ollama"))).toBe("Ollama");
});
