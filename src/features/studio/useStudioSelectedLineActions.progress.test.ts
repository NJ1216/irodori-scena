// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StudioProject } from "../../types";
import { ProjectEditSession } from "./projectEditSession";
import { useStudioSelectedLineActions } from "./useStudioSelectedLineActions";

const mocks = vi.hoisted(() => ({
  generateLine: vi.fn(),
  regenerateLine: vi.fn(),
  project: vi.fn(),
  cancelAutoRender: vi.fn(),
  deleteLines: vi.fn(),
  cleanupLineTakes: vi.fn(),
}));
vi.mock("../../api", () => ({ api: mocks }));
vi.mock("../script/scriptLineDeletionMotion", () => ({ beginScriptLineDeletion: () => ({ complete: vi.fn(), rollback: vi.fn() }) }));

const generatedTake = {
  id: "take-1",
  audioUrl: "/line-1.wav",
  seed: 1,
  quality: "fast",
  stageDirection: "",
  createdAt: 1,
} as const;
const project = {
  version: 1,
  revision: 0,
  id: "project",
  title: "台本",
  characters: [{ id: "cast", name: "キャスト", profile: "", voiceKeywords: "", referenceAudioUrl: "", referenceFile: "", createdAt: 1 }],
  candidates: [],
  scenes: [
    {
      id: "scene-1",
      title: "一",
      lines: [
        {
          id: "line-1",
          text: "一",
          characterId: "cast",
          stageDirection: "",
          takes: [generatedTake],
          selectedTakeId: generatedTake.id,
        },
        { id: "line-2", text: "二", characterId: "cast", stageDirection: "", takes: [], selectedTakeId: null },
      ],
    },
    {
      id: "scene-2",
      title: "二",
      lines: [
        { id: "line-3", text: "三", characterId: "cast", stageDirection: "", takes: [], selectedTakeId: null },
        { id: "line-4", text: "四", characterId: "cast", stageDirection: "", takes: [], selectedTakeId: null },
      ],
    },
  ],
  settings: {
    speechRate: 1,
    steps: 16,
    textCfg: 3,
    voiceCfg: 5,
    seed: 1,
    quality: "fast",
    llmBaseUrl: "",
    llmModel: "",
  },
} as StudioProject;

function baseModel(): Parameters<typeof useStudioSelectedLineActions>[0] {
  const editSession = new ProjectEditSession(() => {});
  editSession.replace(project);
  return {
    editSession,
    projectRef: editSession.projectRef,
    selectedLineIds: [],
    selectedLineIdsRef: { current: [] },
    busy: null,
    busyRef: { current: null },
    setBusy: vi.fn(),
    setNotice: vi.fn(),
    setStatusNotice: vi.fn(),
    setSelectedLineIds: vi.fn(),
    setSelectionAnchorLineId: vi.fn(),
    setFocusedLineId: vi.fn(),
    setBatchGeneratingLineId: vi.fn(),
    stopRef: { current: vi.fn() },
    autoRenderInProgress: { current: false },
    reconcileAutoRenderQueueRef: { current: vi.fn() },
    runWithAutoRenderPriority: async (action) => action(),
    playSelectedLines: vi.fn(),
    applyGeneratedTake: vi.fn(),
    autoRenderPriorityActive: { current: false },
    continuousPlayback: false,
    playingLineId: null,
    deleteLine: vi.fn(),
    selectedLineGenerationRun: { current: 0 },
    selectedLineGenerationTaskRef: { current: Promise.resolve() },
    selectedLineGenerationCancelRef: { current: vi.fn(async () => {}) },
    selectedLineGenerationPauseRef: { current: vi.fn(async () => async () => {}) },
    selectedLineGenerationBatchRef: { current: null },
    selectedLineGenerationActive: false,
    setSelectedLineGenerationActive: vi.fn(),
    selectedLinePlaybackStopRun: { current: 0 },
    selectedLinePlaybackPending: { current: false },
  };
}

beforeEach(() => {
  mocks.generateLine.mockReset().mockResolvedValue({});
  mocks.deleteLines.mockReset().mockResolvedValue({ ...project, revision: 1 });
  mocks.cleanupLineTakes.mockReset().mockResolvedValue({ ...project, revision: 1 });
  mocks.regenerateLine.mockReset().mockResolvedValue({});
  mocks.project.mockReset().mockResolvedValue(project);
  mocks.cancelAutoRender.mockReset().mockResolvedValue({ cancelled: true });
});

describe("selected generation progress", () => {
  it("reflects each completed take before a non-playing batch finishes", async () => {
    const applyGeneratedTake = vi.fn();
    const model = {
      ...baseModel(),
      projectRef: { current: project },
      selectedLineIds: ["line-1", "line-3"],
      selectedLineIdsRef: { current: ["line-1", "line-3"] },
      busy: null,
      busyRef: { current: null },
      stopRef: { current: vi.fn() },
      autoRenderInProgress: { current: false },
      runWithAutoRenderPriority: async (action: () => Promise<void>) => action(),
      playSelectedLines: vi.fn(),
      applyGeneratedTake,
      autoRenderPriorityActive: { current: false },
      continuousPlayback: false,
      playingLineId: null,
      deleteLine: vi.fn(),
      selectedLineGenerationRun: { current: 0 },
      selectedLineGenerationActive: false,
      setSelectedLineGenerationActive: vi.fn(),
      selectedLinePlaybackStopRun: { current: 0 },
      selectedLinePlaybackPending: { current: false },
    };
    const { result } = renderHook(() => useStudioSelectedLineActions(model));
    let finishSecond!: (take: object) => void;
    mocks.generateLine.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishSecond = resolve;
        }),
    );

    let operation!: Promise<void>;
    act(() => {
      operation = result.current.generateSelectedLines(true);
    });
    await waitFor(() => expect(applyGeneratedTake).toHaveBeenCalledWith("scene-1", "line-1", expect.anything(), true, expect.objectContaining({ projectId: project.id })));
    expect(mocks.generateLine).toHaveBeenCalledWith("line-3", "fast", true, undefined, undefined, expect.any(String));
    await act(async () => {
      finishSecond({});
      await operation;
    });
    expect(applyGeneratedTake).toHaveBeenLastCalledWith("scene-2", "line-3", expect.anything(), false, expect.objectContaining({ projectId: project.id }));
  });

  it("keeps the original batch running when the user changes the line selection", async () => {
    const selectedLineIdsRef = { current: ["line-1", "line-3"] };
    const applyGeneratedTake = vi.fn();
    const model = {
      ...baseModel(),
      projectRef: { current: project },
      selectedLineIds: selectedLineIdsRef.current,
      selectedLineIdsRef,
      busy: null,
      busyRef: { current: null },
      stopRef: { current: vi.fn() },
      autoRenderInProgress: { current: false },
      runWithAutoRenderPriority: async (action: () => Promise<void>) => action(),
      playSelectedLines: vi.fn(),
      applyGeneratedTake,
      autoRenderPriorityActive: { current: false },
      continuousPlayback: false,
      playingLineId: null,
      deleteLine: vi.fn(),
      selectedLineGenerationRun: { current: 0 },
      selectedLineGenerationActive: false,
      setSelectedLineGenerationActive: vi.fn(),
      selectedLinePlaybackStopRun: { current: 0 },
      selectedLinePlaybackPending: { current: false },
    };
    const { result } = renderHook(() => useStudioSelectedLineActions(model));
    let finishFirst!: (take: object) => void;
    let interleavedSelectionCommit = false;
    mocks.generateLine
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finishFirst = resolve;
          }),
      )
      .mockImplementationOnce(async () => {
        expect(interleavedSelectionCommit).toBe(false);
        return {};
      });

    let operation!: Promise<void>;
    act(() => {
      operation = result.current.generateSelectedLines(false);
    });
    await waitFor(() => expect(mocks.generateLine).toHaveBeenCalledOnce());

    selectedLineIdsRef.current = ["line-1"];
    const selectionCommit = model.editSession.runServer(async () => {
      interleavedSelectionCommit = true;
    });
    await act(async () => {
      finishFirst({});
      await operation;
      await selectionCommit;
    });

    expect(mocks.generateLine).toHaveBeenNthCalledWith(2, "line-3", "fast", true, undefined, undefined, expect.any(String));
    expect(applyGeneratedTake).toHaveBeenCalledTimes(2);
    expect(model.selectedLineGenerationRun.current).toBe(1);
    expect(interleavedSelectionCommit).toBe(true);
  });
});

describe("context menu destructive actions", () => {
  it("deletes one clicked line on the first invocation while preserving the ordinary confirmation path", async () => {
    const model = baseModel();
    model.selectedLineIds = ["line-1"];
    model.selectedLineIdsRef.current = ["line-1"];
    const { result } = renderHook(() => useStudioSelectedLineActions(model));
    await act(() => result.current.deleteContextLines("line-3"));
    expect(mocks.deleteLines).toHaveBeenCalledOnce();
    expect(mocks.deleteLines).toHaveBeenCalledWith(["line-3"]);
    expect(model.deleteLine).not.toHaveBeenCalled();
    expect(model.setNotice).toHaveBeenCalledWith("1 行を削除しました。");
  });

  it("deletes a selected group on the first invocation", async () => {
    const model = baseModel();
    model.selectedLineIds = ["line-1", "line-3"];
    model.selectedLineIdsRef.current = ["line-1", "line-3"];
    const { result } = renderHook(() => useStudioSelectedLineActions(model));
    await act(() => result.current.deleteContextLines("line-3"));
    expect(mocks.deleteLines).toHaveBeenCalledOnce();
    expect(mocks.deleteLines).toHaveBeenCalledWith(["line-1", "line-3"]);
  });

  it("cleans selected takes on the first invocation", async () => {
    const model = baseModel();
    model.selectedLineIdsRef.current = ["line-1"];
    const { result } = renderHook(() => useStudioSelectedLineActions(model));
    await act(() => result.current.cleanupSelectedTakes("line-1", "all"));
    expect(mocks.cleanupLineTakes).toHaveBeenCalledOnce();
    expect(mocks.cleanupLineTakes).toHaveBeenCalledWith(["line-1"], "all");
    expect(model.setNotice).toHaveBeenCalledWith("テイクの初期化を完了しました（1 テイク）。");
  });
});
