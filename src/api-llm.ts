import { request } from "./api-core";
export type HfGgufVariant = { id: string; quantization: string; files: string[]; shardCount: number; downloadSizeBytes: number };
type LlamaCppRuntimeStatus = { engine: "llama.cpp"; version: string; backend: "cuda" | "cpu"; ready: boolean; path: string | null; job: { state: string; downloadedBytes?: number; totalBytes?: number; error?: string } };
export const llmApi = {
  llmRegistry: () => request<import("./types").LlmRegistry>("/api/llm/registry"),
  createLlmEndpoint: (value: { provider: import("./types").LlmConnection["provider"]; displayName: string; baseUrl: string; credential?: string }) => request<import("./types").LlmEndpoint>("/api/llm/endpoints", { method: "POST", body: JSON.stringify(value) }),
  discoverLlmEndpointModels: (id: string) => request<{ models: string[] }>(`/api/llm/endpoints/${encodeURIComponent(id)}/models`),
  saveLlmEndpointCredential: (id: string, credential: string) =>
    request<import("./types").LlmEndpoint>(`/api/llm/endpoints/${encodeURIComponent(id)}/credential`, {
      method: "PUT",
      body: JSON.stringify({ credential }),
    }),
  deleteLlmEndpointCredential: (id: string) =>
    request<import("./types").LlmEndpoint>(`/api/llm/endpoints/${encodeURIComponent(id)}/credential`, {
      method: "DELETE",
    }),
  deleteLlmEndpoint: (id: string) => request<import("./types").LlmRegistry>(`/api/llm/endpoints/${encodeURIComponent(id)}`, { method: "DELETE" }),
  createLlmCard: (value: { endpointId: string; modelId: string; displayName?: string; source?: string }) => request<import("./types").LlmCard>("/api/llm/cards", { method: "POST", body: JSON.stringify(value) }),
  inspectRemoteLlmModels: (value: { provider: "ollama" | "lmstudio" | "openai"; baseUrl: string; credential?: string }) => request<{ models: string[] }>("/api/llm/remote/models", { method: "POST", body: JSON.stringify(value) }),
  createRemoteLlmSetting: (value: { provider: "ollama" | "lmstudio" | "openai"; baseUrl: string; modelId: string; credential?: string }) =>
    request<{ registry: import("./types").LlmRegistry; card: import("./types").LlmCard }>("/api/llm/remote/settings", {
      method: "POST",
      body: JSON.stringify(value),
    }),
  updateLlmCard: (cardId: string, value: { displayName: string; settings: import("./types").LlmCard["settings"] }) =>
    request<import("./types").LlmCard>(`/api/llm/cards/${encodeURIComponent(cardId)}`, {
      method: "PATCH",
      body: JSON.stringify(value),
    }),
  startLlmCardTest: (cardId: string) => request<import("./types").LlmTestJob>(`/api/llm/cards/${encodeURIComponent(cardId)}/tests`, { method: "POST" }),
  llmCardTest: (jobId: string) => request<import("./types").LlmTestJob>(`/api/llm/tests/${encodeURIComponent(jobId)}`),
  cancelLlmCardTest: (jobId: string) => request<import("./types").LlmTestJob>(`/api/llm/tests/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }),
  setDefaultLlmCard: (id: string) => request<import("./types").LlmRegistry>(`/api/llm/cards/${encodeURIComponent(id)}/default`, { method: "PUT" }),
  deleteLlmCard: (id: string) => request<import("./types").LlmCardDeletion>(`/api/llm/cards/${encodeURIComponent(id)}`, { method: "DELETE" }),
  searchHuggingFace: (query: string, filters: string[] = [], order: "downloads" | "likes" | "name" | "default" = "downloads") =>
    request<{
      models: Array<{
        repoId: string;
        publisher: string;
        revision: string;
        displayName: string;
        downloads: number;
        ggufVariants?: HfGgufVariant[];
        gated: boolean;
        compatibility: "mlx" | "gguf" | "unknown" | "incompatible";
        warning: string | null;
        downloadSizeBytes: number | null;
        inferredTags: Array<{
          kind: "family" | "parameters" | "quantization" | "purpose" | "role" | "compatibility";
          value: string;
        }>;
      }>;
    }>(`/api/llm/huggingface/search?${new URLSearchParams({ q: query, filters: JSON.stringify(filters), order })}`),
  huggingFaceMetadata: (repositories: Array<{ repoId: string; revision: string }>) =>
    request<{ models: Array<{ repoId: string; downloadSizeBytes: number | null; ggufVariants?: HfGgufVariant[] }> }>("/api/llm/huggingface/metadata", {
      method: "POST",
      body: JSON.stringify({ repositories }),
    }),
  huggingFaceTokenStatus: () => request<{ hasToken: boolean }>("/api/llm/huggingface/token"),
  saveHuggingFaceToken: (token: string) => request<{ hasToken: boolean }>("/api/llm/huggingface/token", { method: "PUT", body: JSON.stringify({ token }) }),
  huggingFaceGgufVariants: (repoId: string) => request<{ repoId: string; revision: string; variants: HfGgufVariant[] }>(`/api/llm/huggingface/${repoId.split("/").map(encodeURIComponent).join("/")}/gguf-variants`),
  downloadHuggingFace: (repoId: string, variant?: string) =>
    request<{ id: string; cardId?: string; state: string }>("/api/llm/huggingface/downloads", {
      method: "POST",
      body: JSON.stringify({ repoId, variant }),
    }),
  huggingFaceDownload: (id: string) =>
    request<{
      preparation?: { state: string; stage?: string | null; errorCategory?: string | null; message: string; downloadedBytes: number; totalBytes: number };
      id: string;
      cardId?: string;
      state: string;
      downloadedBytes: number;
      totalBytes: number;
      currentFile?: string;
      error?: string;
      errorCategory?: string;
    }>(`/api/llm/huggingface/downloads/${encodeURIComponent(id)}`),
  cancelHuggingFaceDownload: (id: string) => request(`/api/llm/huggingface/downloads/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  prepareModelRuntime: (id: string, options: { runtimeId?: string; tag?: string }) => request(`/api/llm/cards/${encodeURIComponent(id)}/runtime`, { method: "POST", body: JSON.stringify(options) }),
  cancelModelRuntime: (id: string) => request(`/api/llm/cards/${encodeURIComponent(id)}/runtime/cancel`, { method: "POST" }),
  omlxRuntime: () => request<{ state: string; message: string; ready: boolean; fingerprint: string }>("/api/local-llm/runtime"),
  installOmlxRuntime: () =>
    request<{ state: string; message: string; ready: boolean; fingerprint: string }>("/api/local-llm/runtime/install", {
      method: "POST",
    }),
  cancelOmlxRuntime: () =>
    request<{ state: string; message: string; ready: boolean; fingerprint: string }>("/api/local-llm/runtime/cancel", {
      method: "POST",
    }),
  llamaCppRuntime: (backend?: "cuda" | "cpu") => request<LlamaCppRuntimeStatus>(`/api/local-llm/llama-cpp/runtime${backend ? `?backend=${backend}` : ""}`),
  installLlamaCppRuntime: (backend?: "cuda" | "cpu") => request("/api/local-llm/llama-cpp/runtime/install", { method: "POST", body: JSON.stringify({ backend }) }),
  cancelLlamaCppRuntime: () => request("/api/local-llm/llama-cpp/runtime/cancel", { method: "POST" }),
  deleteLlamaCppRuntime: (backend: "cuda" | "cpu") => request(`/api/local-llm/llama-cpp/runtime/${backend}`, { method: "DELETE" }),
  selectLlamaCppRuntime: (backend: "cuda" | "cpu") => request<LlamaCppRuntimeStatus>("/api/local-llm/llama-cpp/runtime/selection", { method: "PUT", body: JSON.stringify({ backend }) }),
  omlxRuntimes: () => request<import("./types").OmlxRuntimeStatus>("/api/local-llm/runtimes"),
  omlxReleases: () =>
    request<{
      repository: string;
      releases: Array<{ tag: string; name: string; prerelease: boolean; publishedAt: string | null }>;
    }>("/api/local-llm/runtime-releases"),
  installOmlxRuntimeVersion: (tag?: string) =>
    request<import("./types").OmlxRuntimeStatus>("/api/local-llm/runtimes/install", {
      method: "POST",
      body: JSON.stringify({ tag: tag ?? null }),
    }),
  activateOmlxRuntime: (id: string) =>
    request<import("./types").OmlxRuntimeStatus>(`/api/local-llm/runtimes/${encodeURIComponent(id)}/activate`, {
      method: "POST",
    }),
  deleteOmlxRuntime: (id: string) =>
    request<import("./types").OmlxRuntimeStatus>(`/api/local-llm/runtimes/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  mtpAsset: () =>
    request<{
      installed: boolean;
      diskBytes: number;
      cancelable: boolean;
      draftRepo: string;
      draftRevision: string;
      download: { id: string; state: string; downloadedBytes: number; totalBytes: number } | null;
    }>("/api/llm/mtp"),
  downloadMtpAsset: () => request<{ id: string | null; state: string }>("/api/llm/mtp/download", { method: "POST" }),
  cancelMtpAsset: (id: string) => request(`/api/llm/mtp/download/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  scanExternalLlmModels: (path: string) =>
    request<{
      models: Array<{
        id: string;
        displayName: string;
        path: string;
        inferredTags: Array<{
          kind: "family" | "parameters" | "quantization" | "purpose" | "role" | "compatibility";
          value: string;
        }>;
      }>;
      limited: boolean;
      ggufFound: boolean;
    }>("/api/llm/external/scan", { method: "POST", body: JSON.stringify({ path }) }),
  registerExternalLlmModel: (path: string) =>
    request<{ card: import("./types").LlmCard }>("/api/llm/external/register", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
};
