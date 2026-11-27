import { fulfillTimeline, installTimelineMedia } from "./mock-timeline-handlers";
import type { Page, Route } from "@playwright/test";
import metadata from "../../release-metadata.json" with { type: "json" };
import rhubarbCatalog from "../../server/catalogs/rhubarb-runtime.json" with { type: "json" };
import { API_SCHEMA_HASH } from "../../src/generated/api-schema-hash";
import {
  applySimultaneousCue,
  draftFixture,
  extendProjectLines,
  fulfillBatchDelete,
  fulfillCharacterUpdate,
  fulfillHuggingFaceDownload,
  fulfillLoraLibrary,
  fulfillOmlxRuntime,
  fulfillProfileSuggestion,
  fulfillScriptOperations,
  fulfillTts,
  fulfillVoiceDesign,
  json,
  projectFixture,
  registryFixture,
} from "./mock-api-handlers";

type MockApiOptions = {
  generatedTake?: boolean;
  completeTakes?: boolean;
  registeredTts?: boolean;
  downloadsRunning?: boolean;
  runtimeDownloadRunning?: boolean;
  simultaneousCue?: boolean;
  multipleOmlxRuntimes?: boolean;
  lineCount?: number;
  sceneLineCounts?: number[];
  firstRun?: boolean;
  generatedTakeAudioUrl?: string;
  timelineAudioUrl?: string;
  /** Overrides every mock take duration so a test can observe live playback state for longer than a loaded machine's scheduling jitter. */
  takeDurationSeconds?: number;
};

function takeAudioUrl(value?: string) {
  return value ?? "/api/media/takes/take-e2e-1.wav";
}

async function fulfillProjectPersistence(route: Route, project: typeof projectFixture) {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  if (path === "/api/health" && request.method() === "GET") return json(route, { ok: true, apiSchemaHash: API_SCHEMA_HASH }).then(() => true);
  if (path === "/api/project" && request.method() === "GET") return json(route, project).then(() => true);
  if (path === "/api/project/workspace" && request.method() === "GET") return json(route, { path: "/tmp/project.scena", name: "project.scena", isScratch: false }).then(() => true);
  if (path === "/api/project" && request.method() === "PUT") {
    Object.assign(project, request.postDataJSON().project);
    return json(route, project).then(() => true);
  }
  return fulfillProjectPatch(route, project, path);
}

async function fulfillProjectPatch(route: Route, project: typeof projectFixture, path: string) {
  const request = route.request();
  if (path === "/api/characters/order" && request.method() === "PATCH") {
    const body = request.postDataJSON();
    if (body.baseRevision !== project.revision) {
      await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: { code: "project_revision_conflict", currentRevision: project.revision } }) });
      return true;
    }
    const ids = body.characterIds as string[];
    const byId = new Map(project.characters.map((character) => [character.id, character]));
    project.characters = ids.map((id) => byId.get(id)!).filter(Boolean);
    project.revision += 1;
    return json(route, project).then(() => true);
  }
  if (path === "/api/project/metadata" && request.method() === "PATCH") Object.assign(project, request.postDataJSON().changes);
  else if (path === "/api/project/settings" && request.method() === "PATCH") Object.assign(project.settings, request.postDataJSON().changes);
  else if (/^\/api\/lines\/[^/]+$/.test(path) && request.method() === "PATCH") {
    const lineId = decodeURIComponent(path.split("/").at(-1)!);
    const changes = request.postDataJSON().changes;
    for (const scene of project.scenes) scene.lines = scene.lines.map((line) => (line.id === lineId ? { ...line, ...changes } : line));
  } else return false;
  project.revision += 1;
  return json(route, { revision: project.revision }).then(() => true);
}

function createMockProject({ lineCount = 2, sceneLineCounts, simultaneousCue = false, generatedTake = false, completeTakes = false, generatedTakeAudioUrl, takeDurationSeconds }: MockApiOptions) {
  const project = structuredClone(projectFixture);
  extendProjectLines(project, lineCount, sceneLineCounts);
  if (simultaneousCue) applySimultaneousCue(project);
  if (generatedTake) {
    const [line, followingLine] = project.scenes[0].lines;
    line.takes = [
      {
        id: "take-e2e-1",
        audioUrl: takeAudioUrl(generatedTakeAudioUrl),
        seed: 1681853295,
        quality: "fast",
        stageDirection: line.stageDirection,
        durationSeconds: takeDurationSeconds ?? 1.8,
        generationSeconds: 9.5,
        createdAt: 1,
      },
    ];
    line.selectedTakeId = "take-e2e-1";
    if (completeTakes) {
      followingLine.takes = [
        {
          id: "take-e2e-2",
          audioUrl: "/api/media/takes/take-e2e-2.wav",
          seed: 123,
          quality: "fast",
          stageDirection: followingLine.stageDirection,
          durationSeconds: takeDurationSeconds ?? 2.4,
          createdAt: 2,
        },
      ];
      followingLine.selectedTakeId = "take-e2e-2";
      project.scenes
        .flatMap((scene) => scene.lines)
        .slice(2)
        .forEach((item, index) => {
          item.takes = [
            {
              id: `take-e2e-${index + 3}`,
              audioUrl: `/api/media/takes/take-e2e-${index + 3}.wav`,
              seed: index + 3,
              quality: "fast",
              stageDirection: item.stageDirection,
              durationSeconds: takeDurationSeconds ?? 2.4,
              createdAt: index + 3,
            },
          ];
          item.selectedTakeId = `take-e2e-${index + 3}`;
        });
    }
  }
  return project;
}

async function fulfillSystemInfo(route: Route, path: string) {
  if (path === "/api/lipsync/rhubarb")
    return json(route, {
      provider: "Rhubarb",
      version: rhubarbCatalog.version,
      releaseId: rhubarbCatalog.releaseId,
      platform: "darwin-arm64",
      supported: true,
      available: true,
      installed: false,
      ready: false,
      archiveBytes: rhubarbCatalog.platforms["darwin-arm64"].archiveBytes,
      license: rhubarbCatalog.license,
      sourceUrl: rhubarbCatalog.sourceUrl,
      releaseUrl: rhubarbCatalog.releaseUrl,
      job: null,
    }).then(() => true);
  if (path === "/api/pronunciation-dictionary" && route.request().method() === "GET") return json(route, []).then(() => true);
  if (path === "/api/settings/engine-directory") return json(route, { engineDir: "/Users/test/Irodori-TTS", engineDirVerified: true }).then(() => true);
  return false;
}

async function fulfillProjectOrSettings(route: Route, project: typeof projectFixture) {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  if (await fulfillProjectPersistence(route, project)) return true;
  if (await fulfillBatchDelete(route, project)) return true;
  if (path === "/api/project/import-script" && request.method() === "POST") {
    const lines = request.postDataJSON().lines as Array<{ character_id: string; text: string }>;
    let scene = project.scenes.find((item) => !item.lines.length);
    if (!scene) {
      scene = { id: "scene-import", title: "読み込み台本", lines: [] };
      project.scenes.push(scene);
    }
    scene.lines.push(
      ...lines.map((line, index) => ({
        id: `line-import-${index}`,
        characterId: line.character_id,
        text: line.text,
        stageDirection: "",
        takes: [],
        selectedTakeId: null,
      })),
    );
    await json(route, project);
    return true;
  }
  if (/^\/api\/scenes\/[^/]+\/lines\/[^/]+\/cue-mix$/.test(path) && request.method() === "POST") {
    return json(route, {
      audioUrl: "/api/media/cue-mix.wav",
      durationSeconds: 2.6,
      cueId: "cue-e2e",
      signature: "mix-e2e",
    }).then(() => true);
  }
  return false;
}
type LlmRouteOptions = { downloadsRunning: boolean; runtimeDownloadRunning: boolean; omlxState: { optionalInstalled: boolean; recommendedInstalled: boolean } };

async function fulfillLlm(route: Route, { downloadsRunning, runtimeDownloadRunning, omlxState }: LlmRouteOptions) {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  if (await fulfillProfileSuggestion(route)) return true;
  if (await fulfillOmlxRuntime(route, path, runtimeDownloadRunning, omlxState)) return true;
  if (path === "/api/llm/registry") return json(route, registryFixture).then(() => true);
  if (await fulfillHuggingFaceDownload(route, downloadsRunning)) return true;
  if (path === "/api/llm/cards/card-e2e" && request.method() === "PATCH") {
    const body = request.postDataJSON();
    registryFixture.cards[0].displayName = body.displayName;
    registryFixture.cards[0].settings = { ...registryFixture.cards[0].settings, ...body.settings };
    return json(route, registryFixture.cards[0]).then(() => true);
  }
  if (path === "/api/llm/cards/card-e2e/tests" && request.method() === "POST")
    return json(route, {
      id: "llm-test-e2e",
      cardId: "card-e2e",
      state: "queued",
      stage: "queued",
      errorCategory: null,
      error: null,
      checkedAt: null,
    }).then(() => true);
  if (path === "/api/llm/tests/llm-test-e2e")
    return json(route, {
      id: "llm-test-e2e",
      cardId: "card-e2e",
      state: "passed",
      stage: "complete",
      errorCategory: null,
      error: null,
      checkedAt: 1,
    }).then(() => true);
  if (path === "/api/llm/remote/models") return json(route, { models: ["qwen3:8b", "gemma3:12b"] }).then(() => true);
  if (path === "/api/llm/endpoints/endpoint-e2e/models") return json(route, { models: ["qwen3:8b", "gemma3:12b"] }).then(() => true);
  return false;
}
export async function installMockApi(page: Page, options: MockApiOptions = {}) {
  const { registeredTts = false, downloadsRunning = false, runtimeDownloadRunning = false, multipleOmlxRuntimes = false, firstRun = false, timelineAudioUrl } = options;
  if (!firstRun) {
    await page.addInitScript((version) => window.localStorage.setItem(`irodori-scena:first-run-setup:${version}`, "seen"), metadata.version);
  }
  const project = createMockProject(options);
  const ttsSelection = { modelId: registeredTts ? "Aratako/Irodori-TTS-v4.1-Small@2b28324" : null };
  const omlxState = { optionalInstalled: multipleOmlxRuntimes, recommendedInstalled: true };
  let draft: typeof draftFixture & { cancelRequested?: boolean } = { ...draftFixture };
  async function fulfillDraft(route: Route) {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/ai/jobs" && route.request().method() === "POST") {
      await json(route, draft);
      return true;
    }
    if (path === "/api/ai/jobs/draft-e2e/cancel") {
      draft = {
        ...draft,
        status: "cancelled",
        phase: "cancelled",
        cancelRequested: true,
        message: "生成をキャンセルしました。",
      };
      await json(route, draft);
      return true;
    }
    if (path === "/api/ai/jobs/draft-e2e") {
      await json(route, draft);
      return true;
    }
    return false;
  }
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (await fulfillTimeline(route, project, timelineAudioUrl)) return;
    if (await fulfillProjectOrSettings(route, project)) return;
    if (await fulfillSystemInfo(route, path)) return;
    if (await fulfillTts(route, registeredTts, downloadsRunning, ttsSelection)) return;
    if (await fulfillLlm(route, { downloadsRunning, runtimeDownloadRunning, omlxState })) return;
    if (await fulfillLoraLibrary(route, path)) return;
    if (await fulfillVoiceDesign(route, project)) return;
    if (path === "/api/characters/accept") {
      const body = request.postDataJSON();
      const candidate = project.candidates.find((item) => item.id === body.candidate_id);
      const character = {
        id: "cast-voice-design",
        name: body.name,
        profile: body.profile,
        profileDetails: {},
        voiceKeywords: candidate?.keywords ?? "",
        referenceAudioUrl: "/api/media/references/voice-design.wav",
        referenceFile: "references/voice-design.wav",
        createdAt: 4,
      };
      project.characters.push(character);
      project.candidates = project.candidates.filter((item) => item.id !== body.candidate_id);
      return json(route, character);
    }
    if (path === "/api/characters/cast-sara/reference/candidate") {
      project.candidates = [];
      project.scenes[0].lines[0].selectedTakeId = null;
      return json(route, { character: project.characters[0], project, invalidatedLines: 1 });
    }
    if (await fulfillCharacterUpdate(route, project)) return;
    if (await fulfillScriptOperations(route, project)) return;
    if (await fulfillDraft(route)) return;
    return json(route, {});
  });
  await installTimelineMedia(page);
  return project;
}
