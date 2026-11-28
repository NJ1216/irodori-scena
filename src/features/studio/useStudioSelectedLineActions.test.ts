// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StudioProject } from "../../types";
import { ProjectEditSession } from "./projectEditSession";
import { selectedActionLineIds, useStudioSelectedLineActions } from "./useStudioSelectedLineActions";

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

describe("selectedActionLineIds", () => {
  it("orders a sparse multi-selection by script line number", () => {
    expect(selectedActionLineIds(project, ["line-4", "line-1", "line-3"], "line-3")).toEqual(["line-1", "line-3", "line-4"]);
  });

  it("uses only a clicked line outside the current selection", () => {
    expect(selectedActionLineIds(project, ["line-1", "line-2"], "line-4")).toEqual(["line-4"]);
  });

  it("replaces generated rows, creates missing rows, then plays the mixed selection in script order", async () => {
    const runWithAutoRenderPriority = vi.fn(async (action: () => Promise<void>) => action());
    const playSelectedLines = vi.fn();
    const applyGeneratedTake = vi.fn();
    const model = {
      ...baseModel(),
      projectRef: { current: project },
      selectedLineIds: ["line-3", "line-1"],
      selectedLineIdsRef: { current: ["line-3", "line-1"] },
      busy: "line-2",
      busyRef: { current: "line-2" },
      stopRef: { current: vi.fn() },
      autoRenderInProgress: { current: true },
      runWithAutoRenderPriority,
      playSelectedLines,
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

    let finishMissing!: (take: object) => void;
    mocks.generateLine.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishMissing = resolve;
        }),
    );
    let operation!: Promise<void>;
    act(() => {
      operation = result.current.generateSelectedLines(true, "line-3", true);
    });

    await waitFor(() => expect(playSelectedLines).toHaveBeenCalledWith(["line-1"]));
    expect(applyGeneratedTake).toHaveBeenCalledWith("scene-1", "line-1", expect.anything(), true, expect.objectContaining({ projectId: project.id }));
    expect(playSelectedLines).not.toHaveBeenCalledWith(["line-3"]);
    await waitFor(() => expect(mocks.generateLine).toHaveBeenCalledWith("line-3", "fast", true, undefined, undefined, expect.any(String)));
    await act(async () => {
      finishMissing({});
      await operation;
    });

    expect(runWithAutoRenderPriority).toHaveBeenCalledOnce();
    expect(mocks.regenerateLine).toHaveBeenCalledWith("line-1", "fast", true, undefined, undefined, expect.any(String));
    expect(mocks.generateLine).toHaveBeenCalledWith("line-3", "fast", true, undefined, undefined, expect.any(String));
    expect(mocks.regenerateLine.mock.calls[0][5]).toBe(mocks.generateLine.mock.calls[0][5]);
    expect(playSelectedLines).toHaveBeenLastCalledWith(["line-3"]);
  });

  it("keeps generating but does not resume generated playback after playback is stopped", async () => {
    const playbackStopRun = { current: 0 };
    const playSelectedLines = vi.fn();
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
      playSelectedLines,
      applyGeneratedTake,
      autoRenderPriorityActive: { current: false },
      continuousPlayback: false,
      playingLineId: null,
      deleteLine: vi.fn(),
      selectedLineGenerationRun: { current: 0 },
      selectedLineGenerationActive: false,
      setSelectedLineGenerationActive: vi.fn(),
      selectedLinePlaybackStopRun: playbackStopRun,
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
      operation = result.current.generateSelectedLines(true, "line-3", true);
    });
    await waitFor(() => expect(playSelectedLines).toHaveBeenCalledWith(["line-1"]));
    playbackStopRun.current += 1;
    await waitFor(() => expect(mocks.generateLine).toHaveBeenCalledWith("line-3", "fast", true, undefined, undefined, expect.any(String)));
    await act(async () => {
      finishSecond({});
      await operation;
    });

    expect(mocks.generateLine).toHaveBeenCalledWith("line-3", "fast", true, undefined, undefined, expect.any(String));
    expect(playSelectedLines).toHaveBeenCalledTimes(1);
  });
});
