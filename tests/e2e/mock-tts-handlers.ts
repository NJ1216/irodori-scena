import type { Route } from "@playwright/test";
import { json } from "./mock-api-response";

const installedTtsModel = {
  id: "Aratako/Irodori-TTS-v4.1-Small@2b28324",
  displayName: "Irodori-TTS v4.1 Small",
  source: "managed",
  repo: "Aratako/Irodori-TTS-v4.1-Small",
  revision: "2b28324dc263",
  path: "/Users/test/.scena/tts/Irodori-TTS-v4.1-Small",
  codecPath: "/Users/test/.scena/tts/codec",
  codecRevision: "codec-e2e",
  diskBytes: 3_500_641_346,
  verification: "verified",
  installedAt: 1,
  license: "MIT",
  modelCardUrl: "https://huggingface.co/Aratako/Irodori-TTS-v4.1-Small",
  author: "Aratako",
  releasedAt: "2026-08-11",
  generation: "v4.1",
  recommendedOrder: 1,
  legacy: false,
  referenceVoice: true,
  voiceDesign: true,
  combinedReferenceCaption: true,
  tagline: "品質を重視した標準モデル",
  description: "音声品質を重視した標準モデルです。どれを選ぶか迷った場合におすすめです。",
  activeVariantId: "pytorch-fp32",
  installedVariants: [{ id: "pytorch-fp32", precision: "FP32", backend: "pytorch", repo: "Aratako/Irodori-TTS-v4.1-Small", revision: "2b28324dc263", optimizationProfile: "pytorch-fp32" }],
};

const installedAnimeModel = {
  ...installedTtsModel,
  activeVariantId: undefined,
  installedVariants: undefined,
  id: "phasefield-audio/Irodori-TTS-v4.1-Anime@6b259f5",
  displayName: "Irodori-TTS v4.1 Small Anime",
  repo: "phasefield-audio/Irodori-TTS-v4.1-Anime",
  revision: "6b259f5baa5e",
  author: "phasefield-audio",
  releasedAt: "2026-09-04",
  publisher: "phasefield-audio",
  provenance: "third-party-finetune",
  notice: "phasefield-audio氏制作の第三者ファインチューニングモデルです。Aratako氏による制作・公式配布ではありません。",
  tagline: "アニメ調の音声表現に特化した第三者モデル",
  description: "アニメ調の音声データで追加学習された第三者モデルです。",
  recommendedOrder: 3,
};

const installedV3BaseModel = {
  ...installedTtsModel,
  id: "Aratako/Irodori-TTS-500M-v3@236c1e5",
  displayName: "Irodori-TTS v3 Base",
  repo: "Aratako/Irodori-TTS-500M-v3",
  revision: "236c1e565912",
  generation: "v3",
  recommendedOrder: 6,
  legacy: true,
  voiceDesign: false,
  combinedReferenceCaption: false,
  tagline: undefined,
  description: undefined,
};

// A catalogue placeholder for the FP32 variant SCENA derives locally; the add dialog must not list it as a choice.
const derivedFp32Placeholder = {
  id: "mlx-fp32",
  displayName: "MLX FP32（LoRA対応）",
  precision: "FP32",
  backend: "mlx",
  repo: "Aratako/Irodori-TTS-v4.1-Small",
  revision: "2b28324dc263",
  sizeBytes: 0,
  runtimeProfile: "mlx-audio-0.5.0-fp32",
  visible: true,
  available: false,
  derivedLocal: true,
  recommendedOrder: 4,
  unavailableReason: "公式FP32資産とMLX FP16の導入後に選択できます。追加ダウンロードは不要です。",
};

async function fulfillTtsDownload(route: Route, path: string, downloadsRunning: boolean, downloadJob: Record<string, unknown>) {
  const request = route.request();
  if (downloadsRunning && path.match(/^\/api\/tts\/model\/[^/]+\/downloads$/) && request.method() === "POST") return json(route, downloadJob).then(() => true);
  if (downloadsRunning && path === "/api/tts/downloads/tts-download-e2e") return json(route, downloadJob).then(() => true);
  if (downloadsRunning && path === "/api/tts/downloads/tts-download-e2e/cancel") return json(route, { ...downloadJob, state: "cancelled" }).then(() => true);
  return false;
}

export async function fulfillTts(route: Route, registeredTts: boolean, downloadsRunning: boolean, selection: { modelId: string | null }) {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  if (path === "/api/tts/runtime/status") return json(route, { modelId: selection.modelId, state: "ready", error: null }).then(() => true);
  if (path === "/api/project/tts-selection" && request.method() === "PUT") {
    const selected = request.postDataJSON().model_id === installedAnimeModel.id ? installedAnimeModel : installedTtsModel;
    return json(route, {
      engine: { repo: "Aratako/Irodori-TTS", commit: "8224dafb46d", externalId: null },
      model: { repo: selected.repo, revision: selected.revision },
      codecRevision: selected.codecRevision,
      optimizationProfile: "mps-fp32-v1",
    }).then(() => true);
  }
  const downloadJob = {
    id: "tts-download-e2e",
    assetKind: "model",
    assetId: "Aratako/Irodori-TTS-v4.1-Small@2b28324",
    state: "running",
    stage: "モデルを取得中",
    downloadedBytes: 1_000_000_000,
    totalBytes: 3_500_641_346,
    currentFile: "model.safetensors",
    error: null,
  };
  if (await fulfillTtsDownload(route, path, downloadsRunning, downloadJob)) return true;
  if (path === "/api/tts/catalog")
    return json(route, {
      version: 1,
      verified: true,
      source: "test",
      engines: [
        {
          id: "Aratako/Irodori-TTS@8224daf",
          displayName: "Irodori-TTS v4 対応版",
          repo: "Aratako/Irodori-TTS",
          commit: "8224dafb46d",
          installable: true,
          license: "MIT",
        },
      ],
      models: [
        {
          id: "Aratako/Irodori-TTS-v4.1-Small@2b28324",
          displayName: "Irodori-TTS v4.1 Small",
          repo: "Aratako/Irodori-TTS-v4.1-Small",
          revision: "2b28324dc263",
          generation: "v4.1",
          recommendedOrder: 1,
          legacy: false,
          referenceVoice: true,
          voiceDesign: true,
          combinedReferenceCaption: true,
          installable: true,
          license: "MIT",
          precision: "FP32",
          sizeBytes: 3500641346,
          author: "Aratako",
          releasedAt: "2026-08-11",
          tagline: "品質を重視した標準モデル",
          description: "音声品質を重視した標準モデルです。どれを選ぶか迷った場合におすすめです。",
          variants: [
            { id: "pytorch-fp32", displayName: "FP32", precision: "FP32", backend: "pytorch", repo: "Aratako/Irodori-TTS-v4.1-Small", revision: "2b28324dc263", sizeBytes: 3_064_295_596, runtimeProfile: "pytorch-fp32", available: true, recommendedOrder: 2 },
            { id: "mlx-fp16", displayName: "FP16", precision: "FP16", backend: "mlx", repo: "mlx-community/Irodori-TTS-v4.1-Small-fp16", revision: "8be8d9109138", sizeBytes: 1_961_695_550, runtimeProfile: "mlx-audio-0.5.0-fp16", available: true, recommendedOrder: 1 },
            { id: "mlx-8bit", displayName: "8bit", precision: "8bit", backend: "mlx", repo: "mlx-community/Irodori-TTS-v4.1-Small-8bit", revision: "c81956b675ce", sizeBytes: 1_382_100_230, runtimeProfile: "mlx-audio-0.5.0-8bit", available: true, recommendedOrder: 3 },
            derivedFp32Placeholder,
          ],
        },
        {
          ...installedTtsModel,
          id: "Aratako/Irodori-TTS-v4.1-Small-MF@ccc78f5",
          displayName: "Irodori-TTS v4.1 Small MF",
          repo: "Aratako/Irodori-TTS-v4.1-Small-MF",
          revision: "ccc78f5d480b",
          recommendedOrder: 2,
          installable: true,
          precision: "FP32",
          sizeBytes: 3_093_131_788,
          author: "Aratako",
          releasedAt: "2026-09-12",
          tagline: "生成速度を重視した高速モデル",
          description: "生成速度を重視した高速モデルです。待ち時間を短くしたい場合に適しています。",
        },
        {
          ...installedAnimeModel,
          installable: true,
          precision: "FP32",
          sizeBytes: 3_064_295_596,
        },
      ],
    }).then(() => true);
  if (path === "/api/tts/defaults" && request.method() === "PUT") selection.modelId = request.postDataJSON().model_id;
  else if (path !== "/api/tts/registry") return false;
  const selected = [installedTtsModel, installedAnimeModel, installedV3BaseModel].find((model) => model.id === selection.modelId) ?? null;
  return json(route, {
    version: 1,
    libraries: [],
    activeModelId: selection.modelId,
    defaultEngineId: "external:/Users/test/Irodori-TTS",
    defaultModelId: selection.modelId,
    projectSelection: registeredTts ? { model: { repo: "Aratako/Irodori-TTS-500M-v3", revision: "project-v3-revision" } } : null,
    selectedModelCapabilities: selected,
    missingProjectAssets: [],
    models: registeredTts ? [installedTtsModel, installedAnimeModel, installedV3BaseModel] : [],
    engines: [
      {
        id: "external:/Users/test/Irodori-TTS",
        displayName: "Irodori-TTS",
        source: "external",
        repo: null,
        commit: null,
        path: "/Users/test/Irodori-TTS",
        diskBytes: null,
        verification: "unverified",
      },
    ],
  }).then(() => true);
}
