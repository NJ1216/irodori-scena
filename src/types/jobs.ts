import type { CharacterProfile, DialogueLine, StudioProject } from "./project";
export type DraftJob = {
  id: string;
  mode?: "draft" | "direction";
  status: "planning" | "generating" | "completed" | "failed" | "cancelled";
  message: string;
  title: string;
  totalChunks: number;
  currentChunk: number;
  completedChunks: number;
  appendedLines: number;
  appendedCueCount?: number;
  estimatedSeconds: number;
  phase: "starting" | "context" | "planning" | "dialogue" | "repairing" | "notation" | "performance" | "completed" | "failed" | "cancelled";
  cancelRequested?: boolean;
  llmCallCount: number;
  dialogueAttempt: number;
  currentChunkAcceptedCharacters: number;
  currentChunkTargetCharacters: number;
  requestedCharacters: number;
  receivedCharacters: number;
  receivedRecords: number;
  acceptedCharactersTotal: number;
  targetCharacters: number;
  targetMinutes?: number;
  generatedCharacters: number;
  estimatedGeneratedCharacters?: number | null;
  progressUpdatedAt?: number;
  overallProgress: number;
  adaptiveYieldRatio: number;
  yieldSamples: number;
  lastYieldRatio?: number | null;
  loopDetected?: string;
  performanceAttempt: number;
  notationCompletedSteps: number;
  notationTotalSteps: number;
  performanceCompletedLines: number;
  performanceTotalLines: number;
  transitionCompleted: number;
  transitionTotal: number;
  performanceTextCorrections: number;
  /** Set once constraint/notation finishing requires an extra visible step. */
  draftFinishingStepRequired?: boolean;
  /** Set once missing integrated direction requires an independent AI pass. */
  performanceFallbackStepRequired?: boolean;
  contextFallbackReason?: string;
  usedTokens: number;
  tokenUsageAvailable: boolean;
  tokenUsage?: LlmTokenUsage;
  tokenUsageClassification?: LlmUsageClassification;
  transportCallCount?: number;
  plannedDialogueCalls?: number;
  plannedPrimaryCalls?: number;
  plannedReserveCalls?: number;
  usedPrimaryCalls?: number;
  usedReserveCalls?: number;
  processedDevelopments?: number;
  predictedCalls?: number;
  hardCallCap?: number;
  plannedCoverageCalls?: number;
  plannedRecoveryCalls?: number;
  plannedEndingCalls?: number;
  usedCoverageCalls?: number;
  usedRecoveryCalls?: number;
  usedEndingCalls?: number;
  endingAttempted?: boolean;
  endingCompleted?: boolean;
  storyCompleted?: boolean;
  completionReason?: string;
  predictedDialogueCalls?: number;
  generatedSceneCount?: number;
  partialContinuationUsed?: boolean;
  provider?: string;
  model?: string;
  /** Omitted by older servers, which are treated as having reached the target. */
  targetReached?: boolean;
  lengthAccepted?: boolean;
  minimumAcceptableCharacters?: number;
  actualCharacters?: number;
  plannedBlocks?: number;
  completedBlocks?: number;
  supplementUsed?: boolean;
  capacityYieldRatio?: number;
  coreBlocks?: number;
  plannedChapters?: number;
  completedChapters?: number;
  plannedDevelopments?: number;
  completedDevelopments?: number;
  failedDialogueCalls?: number;
  detailPlanningCalls?: number;
  planningFallbackUsed?: boolean;
  planningFallbackReason?: string;
  inputSectionCount?: number;
  authorEndingSourceId?: string;
  authorEndingText?: string;
  authorEndingCompleted?: boolean;
  partialReason?: string;
  shortfallCharacters?: number;
  startedAt: number;
  phaseStartedAt?: number;
  completedAt?: number;
  error?: string;
  renderLineIds?: string[];
  failureCode?: "model_compatibility" | string;
  chunks: Array<{ index: number; title: string; spokenCharacters: number }>;
};

export type { LlmSessionOperation, LlmSessionUsage, LlmTokenUsage, LlmUsageClassification } from "../features/shared/llmUsageTypes";
import type { LlmTokenUsage, LlmUsageClassification } from "../features/shared/llmUsageTypes";

/** Shared wire shape for both AI台本 and AI演出 jobs. */

export type ProgressEvent = {
  sequence: number;
  jobId: string;
  phase: string;
  current: number;
  total: number;
  metrics: Record<string, unknown>;
  timestamp: string;
  terminal: boolean;
};

export type ProfileSuggestionResult = {
  profileDetails: CharacterProfile;
  requestedProfileFields: number;
  acceptedProfileFields: number;
  requestedRelationFields: number;
  acceptedRelationFields: number;
  incompleteFields: string[];
  incompleteTargetIds: string[];
  warnings: string[];
};

export type ProfileSuggestionJob = {
  id: string;
  status: "generating" | "completed" | "failed" | "cancelled";
  phase: "profile" | "relations" | "completed" | "failed" | "cancelled";
  message: string;
  completedRelations: number;
  totalRelations: number;
  result?: ProfileSuggestionResult;
  error?: string;
  cancelRequested?: boolean;
};

export type ExportJob = {
  id: string;
  status: "preparing" | "generating" | "aligning" | "writing" | "completed" | "completed_with_warnings" | "failed" | "cancelled";
  phase?: ExportJob["status"];
  message: string;
  totalLines: number;
  currentLine: number;
  currentLineId?: string | null;
  completedLines: number;
  generatedLines: number;
  alignmentCompletedLines?: number;
  alignmentTotalLines?: number;
  requiresGeneration?: boolean;
  joinOutput?: boolean;
  mode?: "prepare" | "bundle";
  destinationPath?: string | null;
  artifactCount?: number;
  labFailures?: Array<{ lineId: string; lineNumber: number; reason: string }>;
  updateVersion?: number;
  lineUpdates?: Array<{ version: number; sceneId: string; line: DialogueLine }>;
  cancelRequested?: boolean;
  startedAt: number;
  completedAt?: number;
  audioUrl?: string;
  localPath?: string;
  fileName?: string;
  files?: Array<{ localPath: string; audioUrl: string; fileName: string }>;
  error?: string;
};

export type RhubarbInstallJob = {
  id: string;
  state: "queued" | "downloading" | "verifying" | "complete" | "failed" | "cancelled";
  message: string;
  error?: string;
  cancelRequested?: boolean;
  downloadedBytes?: number;
  totalBytes?: number;
};

export type RhubarbStatus = {
  provider: "Rhubarb";
  version: string;
  releaseId: string;
  platform: string | null;
  supported: boolean;
  available: boolean;
  installed: boolean;
  ready: boolean;
  archiveBytes: number;
  license: string;
  sourceUrl: string;
  releaseUrl: string;
  job: RhubarbInstallJob | null;
  japaneseAddon?: { ready: boolean; analysisVersion: string; license: string } | null;
  updateAvailable?: boolean;
  installedReleaseId?: string | null;
};

export type ProjectWorkspace = {
  path: string;
  name: string;
  isScratch: boolean;
};

export type WorkspaceResult = {
  project: StudioProject;
  workspace: ProjectWorkspace;
  moved?: boolean;
  globalCastUpdates?: Array<{ id: string; name: string }>;
};

export type ProjectBackupResult = {
  project: StudioProject;
  backup: { path: string; name: string };
};

export type ProjectOptimizationResult = {
  project: StudioProject;
  beforeBytes: number;
  afterBytes: number;
};
