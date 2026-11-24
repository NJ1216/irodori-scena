// @vitest-environment jsdom
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API_SCHEMA_HASH } from "../../generated/api-schema-hash";
import type { StudioEffectModel } from "./studioEffectTypes";
import { useStudioBootstrap } from "./useStudioBootstrap";

const mocks = vi.hoisted(() => ({
  health: vi.fn(),
  project: vi.fn(),
  workspace: vi.fn(),
  engineSettings: vi.fn(),
  llmRegistry: vi.fn(),
  ttsRegistry: vi.fn(),
  ttsCatalog: vi.fn(),
  prepareDerivedAudio: vi.fn(),
}));
vi.mock("../../api", () => ({ api: mocks }));

const project = { id: "project", title: "台本", scenes: [] };
const registry = { endpoints: [], cards: [], defaultCardId: null };
const READY = "準備できました。キャストを登録して、台本を書き始めましょう。";

function pending<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function studioModel() {
  return {
    editSession: { capture: () => 1, isCurrent: () => true, replace: vi.fn() },
    setNotice: vi.fn(),
    setWorkspace: vi.fn(),
    setConnection: vi.fn(),
    setConnectionReady: vi.fn(),
  };
}

describe("useStudioBootstrap", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.health.mockResolvedValue({ apiSchemaHash: API_SCHEMA_HASH });
    mocks.project.mockResolvedValue(project);
    mocks.workspace.mockResolvedValue({ path: null });
    mocks.prepareDerivedAudio.mockResolvedValue(undefined);
  });

  it("shows the project as soon as it arrives, before slower settings reads finish", async () => {
    const llm = pending<typeof registry>();
    mocks.engineSettings.mockResolvedValue({ engineDir: "", engineDirVerified: false });
    mocks.llmRegistry.mockReturnValue(llm.promise);
    const tts = pending<{ models: [] }>();
    mocks.ttsRegistry.mockReturnValue(tts.promise);
    mocks.ttsCatalog.mockResolvedValue({ models: [] });
    const model = studioModel();
    renderHook(() => useStudioBootstrap(model as unknown as StudioEffectModel));

    await waitFor(() => expect(model.editSession.replace).toHaveBeenCalledWith(project));
    expect(model.setNotice).toHaveBeenCalledWith(READY);
    expect(model.setConnectionReady).not.toHaveBeenCalled();

    llm.resolve(registry);
    await waitFor(() => expect(model.setConnection).toHaveBeenCalled());
    expect(model.setConnectionReady).not.toHaveBeenCalled();
    tts.resolve({ models: [] });
    await waitFor(() => expect(model.setConnectionReady).toHaveBeenCalledWith(true));
  });

  it("keeps the project on screen and reports a failed settings read", async () => {
    mocks.engineSettings.mockResolvedValue({ engineDir: "", engineDirVerified: false });
    mocks.llmRegistry.mockRejectedValue(new Error("registry unavailable"));
    mocks.ttsRegistry.mockResolvedValue({ models: [] });
    mocks.ttsCatalog.mockResolvedValue({ models: [] });
    const model = studioModel();
    renderHook(() => useStudioBootstrap(model as unknown as StudioEffectModel));

    await waitFor(() => expect(model.setConnectionReady).toHaveBeenCalledWith(true));
    expect(model.editSession.replace).toHaveBeenCalledWith(project);
    expect(model.setNotice).toHaveBeenLastCalledWith("起動できません: registry unavailable");
  });

  it("reports a startup failure when the project itself cannot be read", async () => {
    mocks.project.mockRejectedValue(new Error("読み込めません"));
    mocks.engineSettings.mockResolvedValue({ engineDir: "", engineDirVerified: false });
    mocks.llmRegistry.mockResolvedValue(registry);
    mocks.ttsRegistry.mockResolvedValue({ models: [] });
    mocks.ttsCatalog.mockResolvedValue({ models: [] });
    const model = studioModel();
    renderHook(() => useStudioBootstrap(model as unknown as StudioEffectModel));

    await waitFor(() => expect(model.setNotice).toHaveBeenCalledWith("起動できません: 読み込めません"));
    expect(model.editSession.replace).not.toHaveBeenCalled();
  });
});
