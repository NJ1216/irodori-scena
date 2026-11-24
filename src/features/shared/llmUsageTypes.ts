export type LlmUsageClassification = "reported" | "partial" | "estimated";
export type LlmTokenUsage = {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  cachedInputTokens: number;
  unknownUsageCalls?: number;
  unconfirmedInputTokens?: number;
  unattributedTokens?: number;
  inputEstimated: boolean;
  outputEstimated: boolean;
  totalEstimated: boolean;
  cachedInputEstimated: boolean;
};
export type LlmSessionOperation = {
  id: string;
  name: string;
  provider: string;
  model: string;
  status: "running" | "completed" | "failed" | "cancelled";
  startedAt: number;
  completedAt: number | null;
  callCount: number;
  usage: LlmTokenUsage;
  classification: LlmUsageClassification;
};
export type LlmSessionUsage = {
  sessionStartedAt: number;
  total: LlmTokenUsage;
  classification: LlmUsageClassification;
  history: LlmSessionOperation[];
};
