import type { LlmEndpoint } from "../../types";

export function visibleEndpointUrl(endpoint?: LlmEndpoint) {
  return endpoint?.provider === "scena-local" ? "" : (endpoint?.baseUrl ?? "");
}
