// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { StudioProject, Take } from "../../types";
import { api } from "../../api";
import { ProjectEditSession } from "./projectEditSession";
import { useStudioLineActions } from "./useStudioLineActions";

const take: Take = {
  id: "take-1",
  audioUrl: "/media/takes/line-1/take-1.wav",
  seed: 1,
  quality: "fast",
  stageDirection: "",
  createdAt: 1,
};

it("splits and focuses the next line while automatic generation is busy", async () => {
  const project = {
    version: 1,
    revision: 0,
    id: "project",
    title: "台本",
    characters: [],
    candidates: [],
    scenes: [{ id: "scene-1", title: "一", lines: [{ id: "line-1", text: "台詞", characterId: "cast", stageDirection: "", takes: [], selectedTakeId: null }] }],
    settings: { speechRate: 1, steps: 16, textCfg: 3, voiceCfg: 5, seed: 1, quality: "fast", llmBaseUrl: "", llmModel: "" },
  } as StudioProject;
  const next = structuredClone(project);
  next.scenes[0].lines.push({ ...next.scenes[0].lines[0], id: "line-2", text: "" });
  const editSession = new ProjectEditSession(() => {});
  editSession.replace(project);
  vi.spyOn(api, "splitLine").mockResolvedValue(next);
  const setFocusedLineId = vi.fn();
  const { result } = renderHook(() =>
    useStudioLineActions({
      project,
      editSession,
      setNotice: vi.fn(),
      busy: "line-1",
      autoRenderActiveLineId: { current: "line-1" },
      setBusy: vi.fn(),
      setLineAssistantTarget: vi.fn(),
      setFocusedLineId,
      setSelectedLineIds: vi.fn(),
      setSelectionAnchorLineId: vi.fn(),
      playingLineId: null,
      stopRef: { current: vi.fn() },
      updateProject: vi.fn(),
      queueAutoRender: vi.fn(),
      continuousPlaybackWaiters: { current: new Set() },
    }),
  );

  expect(await act(() => result.current.splitLine("scene-1", "line-1", 2))).toBe(true);
  expect(api.splitLine).toHaveBeenCalledWith("scene-1", "line-1", 2);
  expect(setFocusedLineId).toHaveBeenCalledWith("line-2");
});

describe("generated take publication", () => {
  it("updates the synchronous project snapshot, React state, and playback waiters together", () => {
    const project = {
      version: 1,
      revision: 0,
      id: "project",
      title: "台本",
      characters: [],
      candidates: [],
      scenes: [
        {
          id: "scene-1",
          title: "一",
          lines: [
            {
              id: "line-1",
              text: "台詞",
              characterId: "cast",
              stageDirection: "",
              takes: [],
              selectedTakeId: null,
            },
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
    const setProject = vi.fn();
    const editSession = new ProjectEditSession(setProject);
    editSession.replace(project);
    const projectRef = editSession.projectRef;
    const wake = vi.fn();
    const continuousPlaybackWaiters = { current: new Set([wake]) };
    const { result } = renderHook(() =>
      useStudioLineActions({
        project,
        editSession,
        setNotice: vi.fn(),
        busy: null,
        autoRenderActiveLineId: { current: null },
        setBusy: vi.fn(),
        setLineAssistantTarget: vi.fn(),
        setFocusedLineId: vi.fn(),
        setSelectedLineIds: vi.fn(),
        setSelectionAnchorLineId: vi.fn(),
        playingLineId: null,
        stopRef: { current: vi.fn() },
        updateProject: vi.fn(),
        queueAutoRender: vi.fn(),
        continuousPlaybackWaiters,
      }),
    );

    act(() => result.current.applyGeneratedTake("scene-1", "line-1", { take, projectRevision: 7 }));

    const line = projectRef.current!.scenes[0].lines[0];
    expect(line.takes).toEqual([take]);
    expect(line.selectedTakeId).toBe(take.id);
    expect(projectRef.current!.revision).toBe(7);
    expect(setProject).toHaveBeenCalledWith(projectRef.current);
    expect(wake).toHaveBeenCalledOnce();
    expect(continuousPlaybackWaiters.current.size).toBe(0);
  });

  it.each([
    [2, false],
    [1, true],
  ])("queues regeneration only when deleting the final take (count=%s)", async (takeCount, expectedQueue) => {
    const takes = Array.from({ length: takeCount }, (_, index) => ({ ...take, id: `take-${index + 1}` }));
    const line = { id: "line-1", text: "台詞", characterId: "cast", stageDirection: "", takes, selectedTakeId: takes[0].id };
    const project = {
      version: 1,
      revision: 0,
      id: "project",
      title: "台本",
      characters: [],
      candidates: [],
      scenes: [{ id: "scene-1", title: "一", lines: [line] }],
      settings: { speechRate: 1, steps: 16, textCfg: 3, voiceCfg: 5, seed: 1, quality: "fast", llmBaseUrl: "", llmModel: "" },
    } as StudioProject;
    const afterDelete = structuredClone(project);
    afterDelete.scenes[0].lines[0].takes = takes.slice(1);
    afterDelete.scenes[0].lines[0].selectedTakeId = takes[1]?.id ?? null;
    const editSession = new ProjectEditSession(() => {});
    editSession.replace(project);
    const queueAutoRender = vi.fn();
    vi.spyOn(api, "deleteTake").mockResolvedValue(afterDelete);
    const { result } = renderHook(() =>
      useStudioLineActions({
        project,
        editSession,
        setNotice: vi.fn(),
        busy: null,
        autoRenderActiveLineId: { current: null },
        setBusy: vi.fn(),
        setLineAssistantTarget: vi.fn(),
        setFocusedLineId: vi.fn(),
        setSelectedLineIds: vi.fn(),
        setSelectionAnchorLineId: vi.fn(),
        playingLineId: null,
        stopRef: { current: vi.fn() },
        updateProject: vi.fn(),
        queueAutoRender,
        continuousPlaybackWaiters: { current: new Set() },
        autoGenerateEnabledRef: { current: true },
      }),
    );

    await act(() => result.current.deleteTake(line, takes[0]));

    expect(queueAutoRender).toHaveBeenCalledTimes(expectedQueue ? 1 : 0);
    if (expectedQueue) expect(queueAutoRender).toHaveBeenCalledWith(line.id, { mode: "append", cause: "last-take-deleted" });
  });
});
