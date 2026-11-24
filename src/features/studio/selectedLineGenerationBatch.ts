export type SelectedLineGenerationBatch = {
  projectId: string;
  targets: Array<{ lineId: string; signature: string; mode: "append" | "replace"; targetTakeId: string | null; knownTakeIds: string[] }>;
  nextIndex: number;
  completedIds: string[];
  skipped: number;
  replace: boolean;
  playAfter: boolean;
  paused: boolean;
  resumed: boolean;
  cancelled: boolean;
  historyGroupId?: string;
};
