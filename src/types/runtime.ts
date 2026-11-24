export type QualityPreset = "turbo" | "fast" | "quality";
export type LlmConnection = {
  provider: "ollama" | "lmstudio" | "openai" | "scena-local";
  baseUrl: string;
  model: string;
  apiKeyEnabled: boolean;
  /** True when the current endpoint has a secret in the OS credential store. */
  hasApiKey: boolean;
  /** Only used while entering/replacing a key, then immediately cleared. */
  apiKey: string;
  /** Optional local Irodori-TTS checkout. Empty uses the development default. */
  engineDir: string;
  engineDirVerified: boolean;
};
export type MemoryBreakdown = {
  totalBytes: number | null;
  availableBytes: number | null;
  otherUsedBytes: number | null;
  scenaAppBytes: number | null;
  llmBytes: number | null;
  ttsBytes: number | null;
};
export type UnifiedMemorySnapshot = MemoryBreakdown & {
  kind: "unified";
  metalOwner: "llm" | "tts" | null;
  runningOwner?: "llm" | "tts" | null;
  llmResident?: boolean;
  ttsResident?: boolean;
  gpuUtilizationPercent: number | null;
  sampledAt: number;
};
export type SplitMemorySnapshot = {
  kind: "split";
  ram: MemoryBreakdown;
  vram: MemoryBreakdown;
  acceleratorOwner: "llm" | "tts" | null;
  gpuUtilizationPercent: number | null;
  sampledAt: number;
};
export type MemorySnapshot = UnifiedMemorySnapshot | SplitMemorySnapshot;
export type TtsRuntimeStatus = {
  state: "stopped" | "preparing" | "ready" | "in-use" | "skipped" | "failed";
  modelId: string | null;
  stage: string | null;
  message: string | null;
  error: string | null;
  releaseReason: string | null;
  preparationReason?: string | null;
  updatedAt: number;
};
export type LlmEndpoint = {
  id: string;
  provider: LlmConnection["provider"];
  displayName: string;
  baseUrl: string;
  hasCredential: boolean;
};
export type StructuredOutputCapability = {
  state: "constrained" | "schema_validated" | "unsupported" | "unknown";
  reasonCode: string | null;
};
export type LlmCard = {
  id: string;
  endpointId: string;
  modelId: string;
  displayName: string;
  source: "managed" | "external" | "remote";
  runtimeId?: string;
  runtime?: { modelDownloadRequired?: boolean; state: string; runtimeId: string; version?: string; recommended: boolean; job: { id: string; state: string; stage?: string; message: string; errorCategory?: string | null; runtimeId: string } | null };
  mtp: { supported: boolean; draftInstalled: boolean; enabled: boolean };
  localMetadata: {
    repoId?: string;
    format?: string;
    quantization?: string;
    diskBytes?: number;
    capabilities?: string[];
    modelContextLimit?: number | null;
    runtimeContextLimit?: number | null;
    revision?: string;
    path?: string;
    omlxVersion?: string;
    loadState?: "loaded" | "unloaded";
    inferredTags?: Array<{
      kind: "family" | "parameters" | "quantization" | "purpose" | "role" | "compatibility";
      value: string;
    }>;
  } | null;
  settings: {
    contextLimit: number | null;
    thinking: boolean;
    ttlSeconds: number;
    trustRemoteCode: boolean;
    memoryGuard: "safe" | "balanced" | "aggressive";
    mtp?: boolean;
    temperature?: number | null;
    topP?: number | null;
    topK?: number | null;
    minP?: number | null;
    repetitionPenalty?: number | null;
  };
  capabilities?: {
    inputTokenLimit?: number | null;
    outputTokenLimit?: number | null;
    modelContextLimit?: number | null;
    runtimeContextLimit?: number | null;
    backend?: "cuda" | "cpu" | "metal" | null;
    generationMethods: string[];
    source: "user" | "provider-api" | "catalog" | "model-config" | "unknown";
    checkedAt: number | null;
    catalog?: { family: string; modelId: string; sourceUrl: string; verifiedAt: string; fields: string[] };
    structuredOutput?: {
      nonStreaming: StructuredOutputCapability;
      streaming: StructuredOutputCapability;
      checkedAt: number | null;
    };
  } | null;
  lastProbe?: { state: "passed" | "failed"; checkedAt: number; stages?: string[]; errorCategory: string | null } | null;
  testStatus: {
    state: "untested" | "testing" | "passed" | "failed";
    checkedAt: number | null;
    errorCategory: string | null;
  };
  usageHistory: Array<{ feature: string; success: boolean; usedAt: number; error: string | null }>;
};

export type LlmRegistry = { version: number; defaultCardId: string | null; endpoints: LlmEndpoint[]; cards: LlmCard[] };
export type OmlxRuntime = {
  usedByModels?: Array<{ id: string; displayName: string }>;
  deletionBlockedReason?: string | null;
  id: string;
  displayName: string;
  omlxVersion: string;
  source: "scena" | "github-release" | "migrated";
  verification: "verified" | "unverified" | "failed";
  state: "ready" | "missing" | "failed";
  diskBytes: number;
  installedAt: number;
  error: string | null;
  commit: string | null;
  gitRef: string | null;
  path: string;
};
export type OmlxRuntimeCatalogItem = {
  id: string;
  displayName: string;
  omlxVersion: string;
  gitRef: string | null;
  commit: string | null;
  pythonVersion: string;
  mlxVersion: string | null;
  mlxLmVersion: string | null;
  mlxVlmVersion: string | null;
  compatibility: string;
  recommended: boolean;
};
export type OmlxRuntimeStatus = {
  activeRuntimeId: string | null;
  recommendedRuntimeId: string;
  updateAvailable: boolean;
  catalog: OmlxRuntimeCatalogItem[];
  installedRuntimes: OmlxRuntime[];
  job: { id: string | null; runtimeId: string | null; state: string; message: string; error?: string | null };
};
export type LlmCardDeletion = {
  registry: LlmRegistry;
  action: "deleted" | "unregistered";
  source: LlmCard["source"];
  modelFilesDeleted: boolean;
  mtpDeleted: boolean;
  mtpRetainedReason: string | null;
};
export type LlmTestJob = {
  id: string;
  cardId: string;
  state: "queued" | "passed" | "failed" | "cancelled";
  stage: string;
  errorCategory: string | null;
  error: string | null;
  checkedAt: number | null;
};

export type TtsAssetCard = {
  id: string;
  displayName: string;
  source: "managed" | "external";
  repo: string | null;
  commit?: string | null;
  revision?: string | null;
  path?: string;
  diskBytes: number | null;
  verification: "verified" | "unverified" | "failed";
  codecRevision?: string;
  license?: string;
  licenseUrl?: string;
  modelCardUrl?: string;
  author?: string;
  releasedAt?: string;
  tagline?: string;
  description?: string;
  publisher?: string;
  provenance?: "upstream" | "third-party-finetune";
  notice?: string;
  generation?: string;
  referenceVoice?: boolean;
  voiceDesign?: boolean;
  combinedReferenceCaption?: boolean;
  legacy?: boolean;
  recommendedOrder?: number;
  flowParameterization?: "rf_velocity" | "meanflow";
  fixedSteps?: number | null;
  supportsRuntimeCfg?: boolean;
  supportsQualityPresets?: boolean;
  requiredVramBytes?: number;
  libraryId?: string;
  engineId?: string;
  codecPath?: string;
  tokenizerPath?: string;
  activeVariantId?: string;
  installedVariants?: TtsInstalledVariant[];
};
export type TtsInstalledVariant = {
  id: string;
  precision: string;
  backend: "pytorch" | "mlx";
  repo: string;
  revision: string;
  path?: string;
  diskBytes?: number | null;
  optimizationProfile: string;
};
export type TtsLibrary = {
  id: string;
  displayName: string;
  root: string;
  engineId: string;
  enginePath: string;
  pythonPath: string;
  assetRoots?: string[];
  available: boolean;
  checkedAt: number;
  modelCount: number;
};
export type TtsProjectSelection = {
  engine: { repo: string | null; commit: string | null; externalId: string | null };
  model: { repo: string; revision: string } | null;
  codecRevision: string | null;
  optimizationProfile: string;
};
export type TtsRegistry = {
  version: number;
  defaultEngineId: string | null;
  defaultModelId: string | null;
  engines: TtsAssetCard[];
  models: TtsAssetCard[];
  libraries: TtsLibrary[];
  projectSelection: TtsProjectSelection | null;
  activeModelId?: string | null;
  missingProjectAssets?: Array<"engine" | "model">;
  selectedModelCapabilities?: Pick<TtsAssetCard, "generation" | "referenceVoice" | "voiceDesign" | "combinedReferenceCaption" | "legacy" | "recommendedOrder" | "flowParameterization" | "fixedSteps" | "supportsRuntimeCfg" | "supportsQualityPresets"> | null;
};
export type TtsCatalogItem = {
  id: string;
  displayName: string;
  repo: string;
  commit?: string;
  revision?: string;
  precision?: string;
  sizeBytes?: number | null;
  license?: string;
  modelCardUrl?: string;
  author?: string;
  releasedAt?: string;
  tagline?: string;
  description?: string;
  publisher?: string;
  provenance?: "upstream" | "third-party-finetune";
  notice?: string;
  installable: boolean;
  unavailableReason?: string;
  supportedEngineIds?: string[];
  generation?: string;
  referenceVoice?: boolean;
  voiceDesign?: boolean;
  combinedReferenceCaption?: boolean;
  legacy?: boolean;
  recommendedOrder?: number;
  flowParameterization?: "rf_velocity" | "meanflow";
  fixedSteps?: number | null;
  supportsRuntimeCfg?: boolean;
  supportsQualityPresets?: boolean;
  variants?: TtsCatalogVariant[];
};
export type TtsCatalogVariant = {
  id: string;
  displayName: string;
  precision: string;
  backend: "pytorch" | "mlx";
  repo: string;
  revision: string;
  sizeBytes: number;
  runtimeProfile: string;
  visible?: boolean;
  available: boolean;
  /** A placeholder for a variant SCENA derives locally once its prerequisites are installed; it is never a download choice. */
  derivedLocal?: boolean;
  unavailableReason?: string;
  computePrecision?: "fp32" | "bf16";
  checkpointFile?: string;
  quantization?: string;
  recommendedOrder: number;
};
export type TtsCatalog = {
  version: number;
  verified: boolean;
  source: string;
  engines: TtsCatalogItem[];
  models: TtsCatalogItem[];
};
export type TtsInstallJob = {
  id: string;
  assetKind: "engine" | "model";
  assetId: string;
  state: "queued" | "running" | "cancelling" | "cancelled" | "failed" | "complete";
  stage: string;
  downloadedBytes: number;
  totalBytes: number;
  currentFile: string | null;
  error: string | null;
};
export type TtsLibraryScan = {
  root: string;
  displayName: string;
  limited: boolean;
  assetRoots?: string[];
  engines: Array<{ id: string; path: string; pythonPath: string | null }>;
  models: Array<{
    id: string;
    path: string;
    tokenizerPath: string | null;
    displayName: string;
    repo: string | null;
    revision: string | null;
    location: string;
  }>;
  codecs: Array<{ id: string; path: string }>;
  warnings: Array<{ code: string; path: string; message: string }>;
};
export type TtsLibraryModelJob = {
  id: string;
  libraryId: string;
  state: "queued" | "running" | "cancelling" | "cancelled" | "failed" | "complete";
  stage: string;
  processedBytes: number;
  totalBytes: number;
  currentFile: string | null;
  error: string | null;
  modelId: string | null;
  duplicate: boolean;
};
