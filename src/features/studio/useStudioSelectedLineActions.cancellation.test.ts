// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StudioProject } from "../../types";
import { ProjectEditSession } from "./projectEditSession";
import { createRenderJob, nextRenderSequence } from "./renderJobQueue";
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

describe("selected generation cancellation", () => {
  it("resumes at the interrupted row with a new history group after a history pause", async () => {
    const model = baseModel();
    model.selectedLineIdsRef.current = ["line-1", "line-3"];
    let finishInterrupted!: (take: object) => void;
    mocks.generateLine
      .mockResolvedValueOnce({})
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finishInterrupted = resolve;
          }),
      )
      .mockResolvedValueOnce({});
    const { result } = renderHook(() => useStudioSelectedLineActions(model));
    let initial!: Promise<void>;
    act(() => {
      initial = result.current.generateSelectedLines(false);
    });
    await waitFor(() => expect(mocks.generateLine).toHaveBeenCalledTimes(2));
    let resume!: () => Promise<void>;
    const pause = model.selectedLineGenerationPauseRef.current();
    await act(async () => {
      finishInterrupted({});
      resume = await pause;
      await initial;
    });
    model.selectedLineIdsRef.current = ["line-4"];
    await act(async () => resume());
    expect(mocks.generateLine.mock.calls.map((call) => call[0])).toEqual(["line-1", "line-3", "line-3"]);
    expect(mocks.generateLine.mock.calls[0][5]).not.toBe(mocks.generateLine.mock.calls[2][5]);
    expect(model.applyGeneratedTake).toHaveBeenCalledTimes(2);
  });

  it("skips a changed row after pause", async () => {
    const model = baseModel();
    model.selectedLineIdsRef.current = ["line-1", "line-3"];
    let finishInterrupted!: (take: object) => void;
    mocks.generateLine.mockResolvedValueOnce({}).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishInterrupted = resolve;
        }),
    );
    const { result } = renderHook(() => useStudioSelectedLineActions(model));
    let initial!: Promise<void>;
    act(() => {
      initial = result.current.generateSelectedLines(false);
    });
    await waitFor(() => expect(mocks.generateLine).toHaveBeenCalledTimes(2));
    const pause = model.selectedLineGenerationPauseRef.current();
    let resume!: () => Promise<void>;
    await act(async () => {
      finishInterrupted({});
      resume = await pause;
      await initial;
    });
    model.editSession.update((current) => ({ ...current, scenes: current.scenes.map((scene) => ({ ...scene, lines: scene.lines.map((line) => (line.id === "line-3" ? { ...line, text: "変更" } : line)) })) }));
    await act(async () => resume());
    expect(mocks.generateLine).toHaveBeenCalledTimes(2);
    expect(model.setNotice).toHaveBeenCalledWith("line-3 は生成条件が変わったため除外しました。");
  });

  it("does not resume a paused batch after explicit cancellation", async () => {
    const model = baseModel();
    model.selectedLineIdsRef.current = ["line-1"];
    let finishInterrupted!: (take: object) => void;
    mocks.generateLine.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishInterrupted = resolve;
        }),
    );
    const { result } = renderHook(() => useStudioSelectedLineActions(model));
    let initial!: Promise<void>;
    act(() => {
      initial = result.current.generateSelectedLines(false);
    });
    await waitFor(() => expect(mocks.generateLine).toHaveBeenCalledOnce());
    const pause = model.selectedLineGenerationPauseRef.current();
    let resume!: () => Promise<void>;
    await act(async () => {
      finishInterrupted({});
      resume = await pause;
      await initial;
    });
    await act(async () => result.current.cancelSelectedLineGeneration());
    await act(async () => resume());
    expect(mocks.generateLine).toHaveBeenCalledOnce();
    expect(model.selectedLineGenerationBatchRef.current).toBeNull();
  });
});

describe("selected generation cancellation", () => {
  it("does not regenerate a take committed while interruption races with completion", async () => {
    const model = baseModel();
    model.selectedLineIdsRef.current = ["line-3"];
    let finishInterrupted!: (take: object) => void;
    mocks.generateLine.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishInterrupted = resolve;
        }),
    );
    const { result } = renderHook(() => useStudioSelectedLineActions(model));
    let initial!: Promise<void>;
    act(() => {
      initial = result.current.generateSelectedLines(false);
    });
    await waitFor(() => expect(mocks.generateLine).toHaveBeenCalledOnce());
    const pause = model.selectedLineGenerationPauseRef.current();
    let resume!: () => Promise<void>;
    await act(async () => {
      finishInterrupted({});
      resume = await pause;
      await initial;
    });
    model.editSession.update((current) => ({ ...current, scenes: current.scenes.map((scene) => ({ ...scene, lines: scene.lines.map((line) => (line.id === "line-3" ? { ...line, takes: [{ ...generatedTake, id: "committed" }], selectedTakeId: "committed" } : line)) })) }));
    await act(async () => resume());
    expect(mocks.generateLine).toHaveBeenCalledOnce();
    expect(model.applyGeneratedTake).not.toHaveBeenCalled();
  });

  it("does not resume after switching projects during a history pause", async () => {
    const model = baseModel();
    model.selectedLineIdsRef.current = ["line-3"];
    let finishInterrupted!: (take: object) => void;
    mocks.generateLine.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishInterrupted = resolve;
        }),
    );
    const { result } = renderHook(() => useStudioSelectedLineActions(model));
    let initial!: Promise<void>;
    act(() => {
      initial = result.current.generateSelectedLines(false);
    });
    await waitFor(() => expect(mocks.generateLine).toHaveBeenCalledOnce());
    const pause = model.selectedLineGenerationPauseRef.current();
    let resume!: () => Promise<void>;
    await act(async () => {
      finishInterrupted({});
      resume = await pause;
      await initial;
    });
    model.editSession.replace({ ...project, id: "other-project" });
    await act(async () => resume());
    expect(mocks.generateLine).toHaveBeenCalledOnce();
    expect(model.selectedLineGenerationBatchRef.current).toBeNull();
  });
  it("cancels only the selected-line task and its playback", async () => {
    const stop = vi.fn();
    let finishTask!: () => void;
    const task = new Promise<void>((resolve) => {
      finishTask = resolve;
    });
    const model = {
      ...baseModel(),
      selectedLineGenerationActive: true,
      selectedLineGenerationRun: { current: 4 },
      selectedLineGenerationTaskRef: { current: task },
      setSelectedLineGenerationActive: vi.fn(),
      stopRef: { current: stop },
      selectedLinePlaybackStopRun: { current: 0 },
      selectedLinePlaybackPending: { current: true },
      autoGenerateEnabledRef: { current: true },
      autoRenderQueue: { current: [createRenderJob(project, project.scenes[0].lines[1], nextRenderSequence(), { mode: "append", cause: "missing-take" })] },
    };
    const { result } = renderHook(() => useStudioSelectedLineActions(model));

    let cancellation!: Promise<void>;
    act(() => {
      cancellation = result.current.cancelSelectedLineGeneration();
    });
    await waitFor(() => expect(mocks.cancelAutoRender).toHaveBeenCalledOnce());
    let settled = false;
    void cancellation.then(() => {
      settled = true;
    });
    await Promise.resolve();
    expect(settled).toBe(false);
    await act(async () => {
      finishTask();
      await cancellation;
    });

    expect(model.selectedLineGenerationRun.current).toBe(5);
    expect(stop).toHaveBeenCalledOnce();
    expect(mocks.cancelAutoRender).toHaveBeenCalledOnce();
    expect(model.autoGenerateEnabledRef.current).toBe(true);
    expect(model.autoRenderQueue.current.map((job) => job.lineId)).toEqual(["line-2"]);
  });
});

describe("selected manual generation ownership", () => {
  it("does not start the next request when cancellation arrives during its paint boundary", async () => {
    let secondFrame: FrameRequestCallback | null = null;
    let frameCount = 0;
    const requestFrame = vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      frameCount += 1;
      if (frameCount === 1) queueMicrotask(() => callback(performance.now()));
      else secondFrame = callback;
      return frameCount;
    });
    const model = baseModel();
    model.selectedLineIdsRef.current = ["line-1", "line-3"];
    const { result } = renderHook(() => useStudioSelectedLineActions(model));

    let operation!: Promise<void>;
    act(() => {
      operation = result.current.generateSelectedLines(false);
    });
    await waitFor(() => expect(requestFrame).toHaveBeenCalledTimes(2));
    expect(mocks.generateLine).toHaveBeenCalledTimes(1);

    let cancellation!: Promise<void>;
    act(() => {
      cancellation = result.current.cancelSelectedLineGeneration();
    });
    act(() => secondFrame?.(performance.now()));
    await act(async () => {
      await cancellation;
      await operation;
    });

    expect(mocks.generateLine).toHaveBeenCalledTimes(1);
    requestFrame.mockRestore();
  });

  it("keeps a selected manual request cancellable while automatic generation is on", async () => {
    const queuedJob = createRenderJob(project, project.scenes[0].lines[1], nextRenderSequence(), { mode: "append", cause: "missing-take" });
    const process = vi.fn(async () => {});
    const model = {
      ...baseModel(),
      autoGenerateEnabledRef: { current: true },
      autoRenderQueue: { current: [queuedJob] },
      processAutoRenderQueueRef: { current: process },
      runWithAutoRenderPriority: vi.fn(async (action: () => Promise<void>) => action()),
    };
    model.selectedLineIdsRef.current = ["line-1", "line-3"];
    const { result } = renderHook(() => useStudioSelectedLineActions(model));

    await act(() => result.current.generateSelectedLines(true));

    expect(model.runWithAutoRenderPriority).toHaveBeenCalledOnce();
    expect(model.setSelectedLineGenerationActive).toHaveBeenNthCalledWith(1, true);
    expect(model.setSelectedLineGenerationActive).toHaveBeenLastCalledWith(false);
    expect(mocks.regenerateLine).toHaveBeenCalledWith("line-1", "fast", true, undefined, undefined, expect.any(String));
    expect(mocks.generateLine).toHaveBeenCalledWith("line-3", "fast", true, undefined, undefined, expect.any(String));
    expect(model.autoRenderQueue.current).toEqual([queuedJob]);
    expect(process).not.toHaveBeenCalled();
  });

  it("keeps the captured batch when the visible selection is cleared during generation", async () => {
    const model = baseModel();
    model.selectedLineIdsRef.current = ["line-1", "line-3"];
    const { result } = renderHook(() => useStudioSelectedLineActions(model));
    let finishFirst!: (take: object) => void;
    mocks.generateLine.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishFirst = resolve;
        }),
    );

    let operation!: Promise<void>;
    act(() => {
      operation = result.current.generateSelectedLines(false, "line-1");
    });
    await waitFor(() => expect(mocks.generateLine).toHaveBeenCalledWith("line-1", "fast", true, undefined, undefined, expect.any(String)));
    model.selectedLineIdsRef.current = [];
    await act(async () => {
      finishFirst({});
      await operation;
    });

    expect(mocks.generateLine).toHaveBeenLastCalledWith("line-3", "fast", true, undefined, undefined, expect.any(String));
    expect(mocks.generateLine).toHaveBeenCalledTimes(2);
  });
});
