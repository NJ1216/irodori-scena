export type LoraInputRow = { id: string; wavName: string | null; textName: string | null; text: string; caption: string; speakerId: string; durationSeconds: number | null; issues: string[]; blocked?: boolean; relativePath?: string; audioUrl?: string };
export type LoraDataset = { datasetId: string; rows: LoraInputRow[]; folderName?: string; ignoredTextCount?: number };
export type LoraAssetUsage = { scope: "current_project_and_global_casts"; projectId: string; casts: Array<{ id: string; name: string; scope: string }>; takes: Array<{ lineId: string; takeId: string; characterId: string }>; takeCount: number; otherSavedProjectsChecked: false };
export type LoraAsset = { memo?: string; archived?: boolean; archivedAt?: number; id: string; name: string; adapterHash: string; baseModelRepo: string; baseModelRevision: string };
export type LoraJob = { id: string; name: string; status: string; step?: number; totalSteps?: number; error?: string; adapterId?: string };
export type LoraStatus = { supported: boolean; reason?: string; generationSupported?: boolean; generationReason?: string; baseModelRepo?: string; baseModelRevision?: string };
export type LoraStart = {
  sourceAdapterId?: string;
  datasetId: string;
  name: string;
  memo: string;
  mode: "check" | "normal";
  rows: (Pick<LoraInputRow, "id" | "text" | "caption" | "speakerId"> & { excluded?: boolean })[];
  settings?: { maxSteps: number; learningRate: number; batchSize?: number; maxSeconds?: number | null };
};
