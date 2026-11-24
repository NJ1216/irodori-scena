export type ScriptAssistantRow = {
  id: string;
  originalLineId?: string;
  characterId: string;
  characterName: string;
  text: string;
  stageDirection: string;
  speechRate?: number;
  gapSeconds?: number;
  proposalCueId?: string;
  startOffsetSeconds?: number;
};

export type ScriptAssistantGroup = {
  id: string;
  sceneId: string;
  sceneTitle: string;
  atomic: boolean;
  contiguous: boolean;
  rows: ScriptAssistantRow[];
  originalRows: Array<{
    id: string;
    characterId: string;
    characterName: string;
    text: string;
    stageDirection: string;
    enabled: boolean;
    hasTakes: boolean;
  }>;
  warnings: string[];
};

export type ScriptAssistantJob = {
  id: string;
  operation: "insert" | "rewrite" | "paraphrase" | "cast-compose";
  status: "planning" | "generating" | "completed" | "failed" | "cancelled";
  phase: string;
  message: string;
  overallProgress: number;
  cancelRequested?: boolean;
  proposalId?: string;
  sourceSignature?: string;
  groups?: ScriptAssistantGroup[];
  warnings?: string[];
};
