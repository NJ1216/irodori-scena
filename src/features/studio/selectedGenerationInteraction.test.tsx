// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LineGenerationResult, StudioProject, Take } from "../../types";
import { useStudioState } from "./useStudioState";
import { useStudioProjectEditing } from "./useStudioProjectEditing";
import { useStudioLineActions } from "./useStudioLineActions";
import { useStudioPlayback } from "./useStudioPlayback";
import { useStudioAutoRender } from "./useStudioAutoRender";
import { useStudioSelectedLineActions } from "./useStudioSelectedLineActions";
import { useStudioShortcuts } from "./useStudioShortcuts";

const mocks = vi.hoisted(() => ({ generateLine: vi.fn(), cancelAutoRender: vi.fn(), runTimelineSession: vi.fn(), project: vi.fn() }));
vi.mock("../../api", () => ({ api: mocks }));
// Audio transport is deferred; state, shortcuts, batch ownership, priority,
// persistence, playback start/stop, and take publication are the real hooks.
vi.mock("./timelinePlaybackSession", () => ({ runTimelineSession: mocks.runTimelineSession }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function take(lineId: string, suffix: string): Take {
  return { id: `${lineId}-${suffix}`, audioUrl: `/${lineId}-${suffix}.wav`, seed: 1, quality: "fast", stageDirection: "", createdAt: 1 };
}

function fixture(): StudioProject {
  return {
    version: 1,
    revision: 0,
    id: "project",
    title: "台本",
    characters: [{ id: "cast", name: "キャスト", profile: "", voiceKeywords: "", referenceAudioUrl: "", referenceFile: "", createdAt: 1 }],
    candidates: [],
    scenes: [
      {
        id: "scene",
        title: "一",
        lines: Array.from({ length: 12 }, (_, index) => {
          const id = `line-${index + 1}`;
          return { id, characterId: "cast", text: `台詞${index + 1}`, stageDirection: "", takes: [take(id, "old")], selectedTakeId: `${id}-old` };
        }),
      },
    ],
    settings: { speechRate: 1, steps: 16, textCfg: 3, voiceCfg: 5, seed: 1, quality: "fast", llmBaseUrl: "", llmModel: "" },
  } as StudioProject;
}

function useInteraction() {
  const state = useStudioState();
  const editing = useStudioProjectEditing(state);
  const lines = useStudioLineActions({ ...state, ...editing });
  const playback = useStudioPlayback({ ...state, ...editing });
  const autoRender = useStudioAutoRender({ ...state, ...lines, ...playback });
  const selected = useStudioSelectedLineActions({ ...state, ...lines, ...playback, ...autoRender, deleteLine: vi.fn() });
  const model = { ...state, ...editing, ...playback, ...selected };
  useStudioShortcuts({ ...model, requestProjectMenuAction: vi.fn(), openWorkspace: vi.fn(), saveWorkspace: vi.fn(), toggleAutoGeneration: vi.fn() });
  return model;
}

function press(code: string, modifiers: KeyboardEventInit = {}) {
  document.body.dispatchEvent(new KeyboardEvent("keydown", { code, key: code === "Escape" ? "Escape" : code.slice(3), bubbles: true, cancelable: true, ...modifiers }));
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.cancelAutoRender.mockResolvedValue({ cancelled: true });
  mocks.project.mockResolvedValue(fixture());
});
afterEach(cleanup);

describe("selected generation while navigating and playing", () => {
  it("finishes the original ten-line batch after selection changes and continuous playback", async () => {
    const first = deferred<LineGenerationResult>();
    const fifth = deferred<LineGenerationResult>();
    const audio = deferred<boolean>();
    mocks.runTimelineSession.mockReturnValue(audio.promise);
    mocks.generateLine.mockImplementation(async (lineId: string) => ({ take: take(lineId, "new"), projectRevision: Number(lineId.split("-")[1]) }));
    mocks.generateLine.mockImplementationOnce(() => first.promise);
    const { result } = renderHook(useInteraction);
    const selectedIds = Array.from({ length: 10 }, (_, index) => `line-${index + 1}`);
    act(() => {
      result.current.editSession.replace(fixture());
      result.current.setSelectedLineIds(selectedIds);
      result.current.setSelectionAnchorLineId("line-1");
      result.current.setFocusedLineId("line-10");
    });
    act(() => press("KeyR", { metaKey: true, altKey: true }));
    await waitFor(() => expect(mocks.generateLine).toHaveBeenCalledTimes(1));
    const batch = result.current.selectedLineGenerationTaskRef.current;
    const generationRun = result.current.selectedLineGenerationRun.current;

    act(() => {
      result.current.setSelectedLineIds(["line-3"]);
      result.current.setSelectionAnchorLineId("line-3");
      result.current.setFocusedLineId("line-3");
    });
    act(() => press("Space"));
    await waitFor(() => expect(mocks.runTimelineSession).toHaveBeenCalledOnce());
    expect(mocks.runTimelineSession.mock.calls[0][0].focusedLineId).toBe("line-3");
    expect(result.current.continuousPlayback).toBe(true);
    expect(result.current.selectedLineGenerationActive).toBe(true);
    expect(mocks.cancelAutoRender).not.toHaveBeenCalled();

    mocks.generateLine.mockImplementation(async (lineId: string) => (lineId === "line-5" ? fifth.promise : { take: take(lineId, "new"), projectRevision: Number(lineId.split("-")[1]) }));
    await act(async () => first.resolve({ take: take("line-1", "new"), projectRevision: 1 }));
    await waitFor(() => expect(mocks.generateLine).toHaveBeenCalledTimes(5));
    expect(result.current.project?.scenes[0].lines[0].takes.map((item) => item.id)).toEqual(["line-1-old", "line-1-new"]);
    expect(result.current.selectedLineGenerationActive).toBe(true);
    act(() => press("Space"));
    await act(async () => audio.resolve(false));
    expect(result.current.continuousPlayback).toBe(false);
    expect(result.current.selectedLineGenerationRun.current).toBe(generationRun);
    await act(async () => {
      fifth.resolve({ take: take("line-5", "new"), projectRevision: 5 });
      await batch;
    });

    expect(mocks.generateLine.mock.calls.map(([id]) => id)).toEqual(selectedIds);
    expect(new Set(mocks.generateLine.mock.calls.map((call) => call[5])).size).toBe(1);
    expect(mocks.generateLine.mock.calls[0][5]).toEqual(expect.any(String));
    expect(result.current.project?.scenes[0].lines.map((line) => line.takes.length)).toEqual([...Array<number>(10).fill(2), 1, 1]);
    expect(result.current.selectedLineIds).toEqual(["line-3"]);
    expect(result.current.selectedLineGenerationActive).toBe(false);
    expect(result.current.busy).toBeNull();
    expect(result.current.autoGenerateEnabledRef.current).toBe(true);
    expect(mocks.cancelAutoRender).not.toHaveBeenCalled();
  });
});
