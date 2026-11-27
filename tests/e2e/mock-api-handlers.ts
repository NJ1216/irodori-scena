import type { Route } from "@playwright/test";
import type { Take } from "../../src/types/project";

import { projectFixture } from "./mock-api-fixtures";
import { fulfillLineInsertion } from "./mock-line-insertion";
export { draftFixture, projectFixture, registryFixture } from "./mock-api-fixtures";

import { json } from "./mock-api-response";
export { json } from "./mock-api-response";
export { fulfillTts } from "./mock-tts-handlers";

export async function fulfillLineOperations(route: Route, project: typeof projectFixture) {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  if (await fulfillLineInsertion(route, project)) return true;
  const sceneDeletion = path.match(/^\/api\/scenes\/([^/]+)$/);
  if (sceneDeletion && request.method() === "DELETE") {
    project.scenes = project.scenes.filter((scene) => scene.id !== sceneDeletion[1]);
    await json(route, project);
    return true;
  }
  const lineGeneration = path.match(/^\/api\/lines\/([^/]+)\/(generate|regenerate)$/);
  if (lineGeneration && request.method() === "POST") {
    const [, lineId, mode] = lineGeneration;
    const body = request.postDataJSON();
    const line = project.scenes.flatMap((scene) => scene.lines).find((item) => item.id === lineId);
    if (!line) return json(route, {});
    const newTakeId = `take-${lineId}-${line.takes.length + 1}`;
    const take: Take = {
      id: mode === "regenerate" ? (line.selectedTakeId ?? newTakeId) : newTakeId,
      characterId: line.characterId,
      audioUrl: `/api/media/takes/${lineId}.wav`,
      seed: body.seed ?? 1,
      quality: "fast",
      stageDirection: line.stageDirection,
      durationSeconds: 1,
      generationSeconds: 1,
      createdAt: 1,
    };
    if (mode === "regenerate") line.takes = line.takes.map((item) => (item.id === take.id ? take : item));
    else line.takes.push(take);
    line.selectedTakeId = take.id;
    project.revision += 1;
    await json(route, { take, projectRevision: project.revision });
    return true;
  }
  const lineDeletion = path.match(/^\/api\/scenes\/([^/]+)\/lines\/([^/]+)$/);
  if (!lineDeletion || request.method() !== "DELETE") return false;
  const scene = project.scenes.find((item) => item.id === lineDeletion[1]);
  if (scene) scene.lines = scene.lines.filter((line) => line.id !== lineDeletion[2]);
  await json(route, project);
  return true;
}

export async function fulfillCueMemberAddition(route: Route, project: typeof projectFixture) {
  const request = route.request();
  const match = new URL(request.url()).pathname.match(/^\/api\/scenes\/([^/]+)\/lines\/([^/]+)\/cue-members$/);
  if (!match || request.method() !== "POST") return false;
  const [, sceneId, lineId] = match;
  const scene = project.scenes.find((item) => item.id === sceneId);
  const sourceIndex = scene?.lines.findIndex((item) => item.id === lineId) ?? -1;
  if (!scene || sourceIndex < 0) return json(route, {}).then(() => true);
  const source = scene.lines[sourceIndex];
  const cueId = source.cueId ?? `cue-${lineId}`;
  const cueEnd = scene.lines.reduce((last, item, index) => (item.cueId === cueId ? index : last), sourceIndex);
  source.cueId = cueId;
  scene.lines.splice(cueEnd + 1, 0, {
    ...source,
    id: `line-cue-${scene.lines.length + 1}`,
    characterId: request.postDataJSON().character_id,
    text: "",
    stageDirection: "",
    speechRate: 1,
    gapSeconds: 0.7,
    takes: [],
    selectedTakeId: null,
    cueId,
    startOffsetSeconds: 0,
  });
  await json(route, project);
  return true;
}

export async function fulfillScriptOperations(route: Route, project: typeof projectFixture) {
  if (await fulfillCueMemberAddition(route, project)) return true;
  return fulfillLineOperations(route, project);
}

export async function fulfillVoiceDesign(route: Route, project: typeof projectFixture) {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  if (path === "/api/characters/candidates/clear") {
    await json(route, project);
    return true;
  }
  if (path === "/api/characters/candidates" && request.method() === "POST") {
    const body = request.postDataJSON();
    const id = body.kind === "emotion" ? `candidate-${body.emotion}` : "candidate-baseline";
    const candidate = {
      id,
      keywords: body.keywords,
      sampleText: body.sample_text,
      kind: body.kind ?? "baseline",
      emotion: body.emotion ?? null,
      referenceCandidateId: body.reference_candidate_id ?? null,
      seed: 1,
      audioUrl: `/api/media/candidates/${id}.wav`,
      file: `candidates/${id}.wav`,
      createdAt: 3,
    };
    project.candidates = [candidate, ...project.candidates.filter((item) => item.id !== id)];
    await json(route, { candidates: [candidate] });
    return true;
  }
  if (path === "/api/characters/voice-design-suggestion") {
    await json(route, {
      voiceDesign: { gender: "女性", qualities: ["透明感のある"], style: "穏やか", notes: "" },
      baselineText: "こんにちは、今日は穏やかな午後ですね。",
      emotionTexts: {
        normal: "今日は穏やかに進めましょう。",
        joy: "わあ、😊うれしいです。",
        anger: "それは、😠困ります。",
        sorrow: "少し、😢寂しいです。",
        delight: "やった、🥰素敵です。",
      },
    });
    return true;
  }
  if (path !== "/api/characters/voice-design/save") return false;
  const body = request.postDataJSON();
  const existing = body.character_id && project.characters.find((item) => item.id === body.character_id);
  const character = existing ?? {
    id: "cast-voice-design",
    name: body.name,
    profile: body.profile,
    profileDetails: {},
    voiceKeywords: body.voice_keywords,
    referenceAudioUrl: "/api/media/references/voice-design.wav",
    referenceFile: "references/voice-design.wav",
    createdAt: 4,
  };
  if (existing) existing.voiceKeywords = body.voice_keywords;
  else project.characters.push(character);
  project.candidates = [];
  await json(route, { character, project, invalidatedLines: existing ? 1 : 0 });
  return true;
}

export async function fulfillCharacterUpdate(route: Route, project: typeof projectFixture) {
  const request = route.request();
  const match = new URL(request.url()).pathname.match(/^\/api\/characters\/([^/]+)$/);
  if (!match || request.method() !== "PATCH") return false;
  const character = project.characters.find((item) => item.id === match[1]);
  if (!character) return json(route, {}).then(() => true);
  const body = request.postDataJSON();
  Object.assign(character, {
    name: body.name,
    profile: body.profile,
    voiceKeywords: body.voice_keywords,
    profileDetails: body.profile_details,
  });
  return json(route, character).then(() => true);
}

/** Empty LoRA library so the cast editor's mix setting can render without a training backend. */
export async function fulfillLoraLibrary(route: Route, path: string) {
  if (path === "/api/lora/adapters") return json(route, []).then(() => true);
  if (path === "/api/lora/status") return json(route, { supported: true, generationSupported: true }).then(() => true);
  return false;
}

export async function fulfillHuggingFaceDownload(route: Route, enabled: boolean) {
  if (!enabled) return false;
  const request = route.request();
  const path = new URL(request.url()).pathname;
  if (path === "/api/llm/huggingface/token") return json(route, { hasToken: false }).then(() => true);
  if (path === "/api/llm/huggingface/search")
    return json(route, {
      models: [
        {
          repoId: "mlx-community/e2e-model",
          publisher: "mlx-community",
          revision: "revision-e2e",
          displayName: "E2E Model",
          downloads: 10,
          gated: false,
          compatibility: "mlx",
          warning: null,
          downloadSizeBytes: 4_000_000_000,
          inferredTags: [{ kind: "compatibility", value: "MLX" }],
        },
      ],
    }).then(() => true);
  if (path === "/api/llm/huggingface/downloads" && request.method() === "POST") return json(route, { id: "hf-download-e2e", state: "queued" }).then(() => true);
  if (path === "/api/llm/huggingface/downloads/hf-download-e2e")
    return json(route, {
      id: "hf-download-e2e",
      state: "running",
      downloadedBytes: 1_000_000_000,
      totalBytes: 4_000_000_000,
      currentFile: "model.safetensors",
      error: null,
    }).then(() => true);
  if (path === "/api/llm/huggingface/downloads/hf-download-e2e/cancel")
    return json(route, {
      id: "hf-download-e2e",
      state: "cancelled",
      downloadedBytes: 1_000_000_000,
      totalBytes: 4_000_000_000,
    }).then(() => true);
  return false;
}

export async function fulfillProfileSuggestion(route: Route) {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  const result = {
    profileDetails: {
      background: "雨の日の帰り道で、相手を助けたことから親しくなった。",
      castRelations: { "cast-ren": { address: "先輩", relationship: "互いに本音を言える幼なじみ。" } },
    },
    requestedProfileFields: 1,
    acceptedProfileFields: 1,
    requestedRelationFields: 2,
    acceptedRelationFields: 2,
    incompleteFields: [],
    incompleteTargetIds: [],
    warnings: [],
  };
  if (path === "/api/characters/profile-suggestion" && request.method() === "POST") return json(route, result).then(() => true);
  if (path === "/api/characters/profile-suggestion/jobs" && request.method() === "POST")
    return json(route, {
      id: "profile-e2e",
      status: "generating",
      phase: "profile",
      message: "人物設定を考えています…",
      completedRelations: 0,
      totalRelations: 1,
    }).then(() => true);
  if (path === "/api/characters/profile-suggestion/jobs/profile-e2e/cancel" && request.method() === "POST")
    return json(route, {
      id: "profile-e2e",
      status: "cancelled",
      phase: "cancelled",
      message: "キャンセルしました。",
      completedRelations: 0,
      totalRelations: 1,
      cancelRequested: true,
    }).then(() => true);
  if (path === "/api/characters/profile-suggestion/jobs/profile-e2e/events") {
    const event = {
      sequence: 1,
      jobId: "profile-e2e",
      phase: "completed",
      current: 1,
      total: 1,
      metrics: { status: "completed", message: "キャスト設定の提案が完了しました。" },
      timestamp: "2026-08-28T00:00:00Z",
      terminal: true,
    };
    return route
      .fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: `id: 1\nevent: progress\ndata: ${JSON.stringify(event)}\n\n`,
      })
      .then(() => true);
  }
  if (path === "/api/characters/profile-suggestion/jobs/profile-e2e")
    return json(route, {
      id: "profile-e2e",
      status: "completed",
      phase: "completed",
      message: "完了",
      completedRelations: 1,
      totalRelations: 1,
      result,
    }).then(() => true);
  return false;
}

export function applySimultaneousCue(project: typeof projectFixture) {
  const [head, tail] = project.scenes[0].lines;
  Object.assign(head, { cueId: "cue-e2e", startOffsetSeconds: 0 });
  Object.assign(tail, { cueId: "cue-e2e", startOffsetSeconds: 0.2 });
  project.characters.push({ ...project.characters[0], id: "character-e2e-3", name: "三人目", avatarUrl: "/api/media/avatars/third.png", avatarVersion: 1 });
}

export async function fulfillBatchDelete(route: Route, project: typeof projectFixture) {
  const request = route.request();
  if (new URL(request.url()).pathname !== "/api/lines/batch-delete" || request.method() !== "POST") return false;
  const removed = new Set<string>(request.postDataJSON().line_ids);
  project.scenes.forEach((scene) => {
    scene.lines = scene.lines.filter((line) => !removed.has(line.id));
  });
  return json(route, project).then(() => true);
}

function deletedRuntimeId(route: Route, path: string) {
  if (route.request().method() !== "DELETE") return null;
  return path.match(/^\/api\/local-llm\/runtimes\/([^/]+)$/)?.[1] ?? null;
}

export async function fulfillOmlxRuntime(route: Route, path: string, runtimeDownloadRunning: boolean, state: { optionalInstalled: boolean; recommendedInstalled: boolean }) {
  const deleted = deletedRuntimeId(route, path);
  if (deleted === "release-v0.6.3") state.optionalInstalled = false;
  else if (deleted === "scena-test") state.recommendedInstalled = false;
  const catalog = [
    {
      id: "scena-test",
      displayName: "SCENA動作確認版",
      omlxVersion: "0.6.4",
      gitRef: "1d7826185c5b",
      commit: "1d7826185c5b5b69b38b27cbe57d7597b7551fd7",
      pythonVersion: "3.12",
      mlxVersion: "0.32.0",
      mlxLmVersion: "0.31.3",
      mlxVlmVersion: "0.6.3",
      compatibility: "このSCENA版で動作確認済み",
      recommended: true,
    },
  ];
  const job = runtimeDownloadRunning
    ? {
        id: "runtime-e2e",
        runtimeId: "release-v0.6.4",
        state: "downloading",
        message: "oMLXと必要なライブラリを取得しています。",
      }
    : { id: null, runtimeId: null, state: "idle", message: "" };
  const recommended = {
    id: "scena-test",
    displayName: "SCENA動作確認版",
    omlxVersion: "0.6.4",
    source: "scena",
    verification: "verified",
    state: "ready",
    diskBytes: 410_504_092,
    installedAt: 1,
    error: null,
    commit: "1d7826185c5b5b69b38b27cbe57d7597b7551fd7",
    gitRef: "1d7826185c5b5b69b38b27cbe57d7597b7551fd7",
    path: "/runtime",
  };
  const optional = {
    id: "release-v0.6.3",
    displayName: "v0.6.3",
    omlxVersion: "v0.6.3",
    source: "github-release",
    verification: "verified",
    state: "ready",
    diskBytes: 1_073_741_824,
    installedAt: 2,
    error: null,
    commit: "b".repeat(40),
    gitRef: "v0.6.3",
    path: "/runtime-v0.6.3",
  };
  const installedRuntimes = [...(state.recommendedInstalled ? [recommended] : []), ...(state.optionalInstalled ? [optional] : [])];
  const status = {
    activeRuntimeId: state.recommendedInstalled ? "scena-test" : null,
    recommendedRuntimeId: "scena-test",
    updateAvailable: false,
    catalog,
    installedRuntimes,
    job,
  };
  if (path === "/api/local-llm/runtimes") return json(route, status).then(() => true);
  if (path === "/api/local-llm/runtime-releases")
    return json(route, {
      repository: "jundot/omlx",
      releases: [
        { tag: "v0.6.4", name: "0.6.4", prerelease: false, publishedAt: "2026-08-29T17:05:15Z" },
        { tag: "v0.6.3", name: "0.6.3", prerelease: false, publishedAt: "2026-08-27T17:04:00Z" },
      ],
    }).then(() => true);
  if (path === "/api/local-llm/runtimes/install") return json(route, status).then(() => true);
  if (path === "/api/local-llm/runtime/cancel") return json(route, { ...status, job: { ...job, state: "cancelled" } }).then(() => true);
  if (deleted) return json(route, status).then(() => true);
  return false;
}

export function extendProjectLines(project: typeof projectFixture, lineCount: number, sceneLineCounts?: number[]) {
  lineCount = sceneLineCounts?.reduce((sum, count) => sum + count, 0) ?? lineCount;
  if (lineCount <= project.scenes[0].lines.length) return;
  const templates = structuredClone(project.scenes[0].lines);
  project.scenes[0].lines = Array.from({ length: lineCount }, (_, index) => ({
    ...structuredClone(templates[index % templates.length]),
    id: `line-${index + 1}`,
    text: `${templates[index % templates.length].text} ${index + 1}`,
    takes: [],
    selectedTakeId: null,
  }));
  if (sceneLineCounts) {
    const lines = project.scenes[0].lines;
    let offset = 0;
    project.scenes = sceneLineCounts.map((count, index) => {
      const scene = { id: `scene-${index + 1}`, title: `${index + 1}章`, lines: lines.slice(offset, offset + count) };
      offset += count;
      return scene;
    });
  }
}
