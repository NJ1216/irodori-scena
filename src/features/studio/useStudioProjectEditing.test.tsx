// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StudioProject } from "../../types";
import { useStudioProjectEditing } from "./useStudioProjectEditing";
import { useProjectEditSession } from "./useProjectEditSession";
import { queueProjectSave, useProjectPersistenceState, waitForProjectPersistence } from "./projectPersistence";
import { MEANFLOW_MODEL_REPO, MEANFLOW_MODEL_REVISION } from "../shared/ttsSampling";

const mocks = vi.hoisted(() => ({ saveProject: vi.fn(), patchProjectLine: vi.fn(), patchProjectMetadata: vi.fn(), patchProjectSettings: vi.fn(), clearCandidateScope: vi.fn(), cancelAutoRender: vi.fn() }));
vi.mock("../../api", () => ({ api: { ...mocks } }));

const project = (): StudioProject => ({
  version: 1,
  revision: 0,
  id: "project-1",
  title: "台本",
  characters: [],
  candidates: [],
  scenes: [
    {
      id: "scene-1",
      title: "駅前",
      lines: [
        {
          id: "line-1",
          characterId: "cast-1",
          text: "台詞",
          stageDirection: "静かに",
          takes: [],
          selectedTakeId: null,
        },
      ],
    },
  ],
  settings: {
    speechRate: 1,
    steps: 16,
    textCfg: 1.5,
    voiceCfg: 2,
    seed: 1,
    quality: "fast",
    llmBaseUrl: "",
    llmModel: "",
  },
});

it("does not mark a failed pending save as persisted when an older save succeeds", async () => {
  let finishFirst: (() => void) | undefined;
  mocks.saveProject
    .mockReset()
    .mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          finishFirst = resolve;
        }),
    )
    .mockRejectedValueOnce(new Error("disk full"));
  const { result } = renderHook(() => useProjectPersistenceState());
  const model = { ...result.current, setNotice: vi.fn() };
  const first = queueProjectSave(model, project(), "saved");
  const latest = queueProjectSave(model, { ...project(), title: "unsaved edit" }, "saved");
  finishFirst?.();
  await expect(first).resolves.toBe(true);
  await expect(latest).resolves.toBe(false);
  await expect(waitForProjectPersistence(model)).resolves.toBe(false);
  expect(model.projectSavedVersion.current).toBe(1);
  expect(model.projectSaveVersion.current).toBe(2);
});

function renderEditing(autoGenerate = false) {
  const setNotice = vi.fn();
  const setStatusNotice = vi.fn();
  const autoRenderQueue = { current: [] as import("./renderJobQueue").RenderJob[] };
  const autoRenderInProgress = { current: false };
  const autoRenderActiveLineId = { current: null as string | null };
  const { result } = renderHook(() => {
    const session = useProjectEditSession(setNotice);
    const editing = useStudioProjectEditing({
      ...session,
      setNotice,
      setStatusNotice,
      tabRef: { current: "script" },
      focusedTextInput: { current: null },
      autoGenerateEnabledRef: { current: autoGenerate },
      autoRenderQueue,
      autoRenderInProgress,
      autoRenderActiveLineId,
      processAutoRenderQueueRef: { current: async () => {} },
      busyRef: { current: null },
      tab: "script",
      setTab: vi.fn(),
      busy: null,
      continuousPlayback: false,
      autoScrollEnabled: false,
      setPlaybackHoverFollow: vi.fn(),
      setExportHoverFollow: vi.fn(),
    });
    return { ...session, ...editing, autoRenderQueue, autoRenderInProgress, autoRenderActiveLineId };
  });
  act(() => result.current.editSession.replace(project()));
  return { result, setNotice, setStatusNotice };
}

async function testBatchRenderHistoryLink() {
  const { result } = renderEditing(true);
  const initial = project();
  initial.scenes[0].lines = ["line-1", "line-2", "line-3"].map((id) => ({ ...initial.scenes[0].lines[0], id }));
  act(() => result.current.editSession.replace(initial));

  await act(async () => result.current.adjustLineNumericField(["line-1", "line-2", "line-3"], "voiceCfg", [1]));
  await act(() => result.current.waitForProjectPersistence());

  expect(mocks.saveProject).toHaveBeenCalledTimes(1);
  expect(result.current.autoRenderQueue.current.map((job) => job.lineId)).toEqual(["line-1", "line-2", "line-3"]);
  expect(result.current.autoRenderQueue.current.map((job) => job.historyBaseRevision)).toEqual([0, 0, 0]);
}

describe("useStudioProjectEditing", () => {
  beforeEach(() => {
    mocks.saveProject.mockReset().mockImplementation(async (value) => value);
    mocks.patchProjectLine.mockReset().mockResolvedValue({ revision: 1 });
    mocks.patchProjectMetadata.mockReset().mockResolvedValue({ revision: 1 });
    mocks.patchProjectSettings.mockReset().mockResolvedValue({ revision: 1 });
    mocks.clearCandidateScope.mockReset().mockImplementation(async () => project());
    mocks.cancelAutoRender.mockReset().mockResolvedValue({ cancelled: true });
  });

  it("replaces the generation notice after clearing baseline candidates", async () => {
    const { result, setNotice, setStatusNotice } = renderEditing();

    await act(() => result.current.clearCandidateScope("baseline"));

    // The candidate list inside the open dialog already shows the result, so it must not raise the overlay.
    expect(setStatusNotice).toHaveBeenLastCalledWith("基準ボイス候補を消去しました。");
    expect(setNotice).not.toHaveBeenCalledWith("基準ボイス候補を消去しました。");
  });

  it("persists stage-direction typing only when the line content is committed", async () => {
    const { result } = renderEditing();

    act(() => {
      result.current.updateLine("scene-1", "line-1", { stageDirection: "息を" });
      result.current.updateLine("scene-1", "line-1", { stageDirection: "息を潜めて" });
    });
    expect(mocks.patchProjectLine).not.toHaveBeenCalled();

    await act(() => result.current.commitLineContent("line-1", false));
    expect(mocks.patchProjectLine).toHaveBeenCalledOnce();
    expect(mocks.patchProjectLine.mock.calls[0][2]).toEqual({ stageDirection: "息を潜めて" });
  });

  it("queues committed line speech rate and CFG changes only after saving", async () => {
    const { result } = renderEditing(true);
    await act(async () => result.current.updateLine("scene-1", "line-1", { speechRate: 1.2 }));
    await act(() => result.current.waitForProjectPersistence());
    expect(result.current.autoRenderQueue.current).toHaveLength(1);
    expect(result.current.autoRenderQueue.current[0].mode).toBe("append");

    await act(async () => result.current.updateLine("scene-1", "line-1", { textCfg: 2 }));
    await act(() => result.current.waitForProjectPersistence());
    expect(result.current.autoRenderQueue.current).toHaveLength(1);
    expect(result.current.autoRenderQueue.current[0].renderSignature).not.toBe("");
  });

  it("queues only changed lines in a numeric batch", async () => {
    const { result } = renderEditing(true);
    await act(async () => result.current.setLineNumericField(["line-1"], "voiceCfg", 2));
    await act(() => result.current.waitForProjectPersistence());
    expect(result.current.autoRenderQueue.current).toHaveLength(1);

    await act(async () => result.current.setLineNumericField(["line-1"], "voiceCfg", 2));
    await act(() => result.current.waitForProjectPersistence());
    expect(result.current.autoRenderQueue.current.map((job) => job.lineId)).toEqual(["line-1"]);
  });

  it("saves three selected CFG changes once and links their auto renders to that revision", testBatchRenderHistoryLink);

  it("queues committed CFG changes even when MeanFlow ignores CFG in its render signature", async () => {
    const { result } = renderEditing(true);
    const meanflow = project();
    meanflow.ttsSelection = { model: { repo: MEANFLOW_MODEL_REPO, revision: MEANFLOW_MODEL_REVISION } } as StudioProject["ttsSelection"];
    act(() => result.current.editSession.replace(meanflow));
    await act(async () => result.current.updateLine("scene-1", "line-1", { captionCfg: 4 }));
    await act(() => result.current.waitForProjectPersistence());
    expect(result.current.autoRenderQueue.current.map((job) => job.lineId)).toEqual(["line-1"]);
  });

  it("requests interruption only when the edited line is currently rendering", () => {
    const { result } = renderEditing(true);
    result.current.autoRenderInProgress.current = true;
    result.current.autoRenderActiveLineId.current = "another-line";
    act(() => result.current.queueAutoRender("line-1"));
    expect(mocks.cancelAutoRender).not.toHaveBeenCalled();
    result.current.autoRenderActiveLineId.current = "line-1";
    act(() => result.current.queueAutoRender("line-1"));
    expect(mocks.cancelAutoRender).toHaveBeenCalledExactlyOnceWith("line-1");
    expect(result.current.autoRenderQueue.current).toHaveLength(1);
  });

  it("waits for a committed negative gap to be persisted", async () => {
    let finishSave: (() => void) | undefined;
    mocks.patchProjectLine.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishSave = () => resolve({ revision: 1 });
        }),
    );
    const { result } = renderEditing();

    act(() => result.current.updateLine("scene-1", "line-1", { gapSeconds: -0.5 }));
    expect(result.current.isProjectPersistencePending()).toBe(true);
    let settled = false;
    const waiting = result.current.waitForProjectPersistence().then((value) => {
      settled = true;
      return value;
    });
    await Promise.resolve();
    expect(settled).toBe(false);

    finishSave?.();
    await expect(waiting).resolves.toBe(true);
    expect(mocks.patchProjectLine.mock.calls[0][2]).toEqual({ gapSeconds: -0.5 });
    expect(result.current.isProjectPersistencePending()).toBe(false);
  });

  it("keeps only the latest pending snapshot while a save is running", async () => {
    let finishFirst: (() => void) | undefined;
    mocks.patchProjectLine
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finishFirst = () => resolve({ revision: 1 });
          }),
      )
      .mockResolvedValue({ revision: 2 });
    const { result } = renderEditing();

    act(() => {
      result.current.updateLine("scene-1", "line-1", { gapSeconds: 1 });
      result.current.updateLine("scene-1", "line-1", { gapSeconds: 2 });
      result.current.updateLine("scene-1", "line-1", { gapSeconds: 3 });
    });
    expect(mocks.patchProjectLine).toHaveBeenCalledOnce();
    finishFirst?.();
    await act(() => result.current.waitForProjectPersistence());
    expect(mocks.patchProjectLine).toHaveBeenCalledTimes(2);
    expect(mocks.patchProjectLine.mock.calls[1][2]).toEqual({ gapSeconds: 3 });
  });
});
