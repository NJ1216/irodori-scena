import type { LlmEndpoint } from "../../types";

export const ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1";

const providerLabels: Record<LlmEndpoint["provider"], string> = {
  ollama: "Ollama",
  lmstudio: "LM Studio",
  openai: "OpenAI互換",
  "scena-local": "SCENA",
};

export function visibleEndpointUrl(endpoint?: LlmEndpoint) {
  return endpoint?.provider === "scena-local" ? "" : (endpoint?.baseUrl ?? "");
}

/** The official Anthropic API is stored as an OpenAI-compatible endpoint; the server translates it. */
export function isAnthropicEndpoint(endpoint?: Pick<LlmEndpoint, "provider" | "baseUrl">) {
  if (endpoint?.provider !== "openai") return false;
  try {
    const url = new URL(endpoint.baseUrl.trim());
    const path = url.pathname.replace(/\/+$/, "");
    return url.protocol === "https:" && url.hostname === "api.anthropic.com" && (url.port === "" || url.port === "443") && (path === "" || path === "/v1");
  } catch {
    return false;
  }
}

export function llmProviderLabel(endpoint: LlmEndpoint) {
  return isAnthropicEndpoint(endpoint) ? "Anthropic" : providerLabels[endpoint.provider];
}
