import { readFileAsBase64, request } from "./api-core";
import type { LoraAsset, LoraAssetUsage, LoraDataset, LoraJob, LoraStart, LoraStatus } from "./types/lora";
export const loraApi = {
  status: () => request<LoraStatus>("/api/lora/status"),
  adapters: (includeArchived = false) => request<LoraAsset[]>(includeArchived ? "/api/lora/adapters?includeArchived=true" : "/api/lora/adapters"),
  archivedAdapters: () => request<LoraAsset[]>("/api/lora/adapters/archived"),
  adapterUsage: (id: string) => request<LoraAssetUsage>(`/api/lora/adapters/${encodeURIComponent(id)}/usage`),
  deleteAdapter: (id: string) => request<LoraAsset>(`/api/lora/adapters/${encodeURIComponent(id)}`, { method: "DELETE" }),
  restoreAdapter: (id: string) => request<LoraAsset>(`/api/lora/adapters/${encodeURIComponent(id)}/restore`, { method: "POST" }),
  updateAdapter: (id: string, payload: { name: string; memo: string }) => request<LoraAsset>(`/api/lora/adapters/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  jobs: () => request<LoraJob[]>("/api/lora/jobs"),
  job: (id: string) => request<LoraJob>(`/api/lora/jobs/${encodeURIComponent(id)}`),
  cancel: (id: string) => request<LoraJob>(`/api/lora/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  start: (payload: LoraStart) => request<LoraJob>("/api/lora/jobs", { method: "POST", body: JSON.stringify(payload) }),
  folderInputs: (path: string) => request<LoraDataset>("/api/lora/inputs/folder", { method: "POST", body: JSON.stringify({ path }) }),
  async inputs(files: File[]) {
    const encoded = await Promise.all(files.map(async (file) => ({ name: file.name, dataBase64: await readFileAsBase64(file) })));
    return request<LoraDataset>("/api/lora/inputs", { method: "POST", body: JSON.stringify({ files: encoded }) });
  },
  importAdapter: (payload: { path: string; name: string; memo: string; baseModelRepo: string; baseModelRevision: string }) => request<LoraAsset>("/api/lora/adapters/import", { method: "POST", body: JSON.stringify(payload) }),
};
