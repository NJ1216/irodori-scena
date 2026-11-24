import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import fixture from "../../../tests/fixtures/project-contract.json";
import { ApiError } from "../../api-error";
import type { StudioProject } from "../../types";
import { ProjectEditSession } from "./projectEditSession";
import type { StudioEffectModel } from "./studioEffectTypes";
import { useStudioExportMonitor } from "./useStudioExportMonitor";
import { useStudioDraftMonitor } from "./useStudioDraftMonitor";

const api = vi.hoisted(() => ({ exportJobEvents: vi.fn(), aiJobEvents: vi.fn(), exportJob: vi.fn(), aiJob: vi.fn(), project: vi.fn() }));
vi.mock("../../api", () => ({ api }));
function model() {
  const editSession = new ProjectEditSession(vi.fn());
  editSession.replace(structuredClone(fixture) as StudioProject);
  return {
    editSession,
    exportUpdateVersion: { current: 0 },
    autoGenerationRequestRef: { current: 0 },
    autoGenerateEnabledRef: { current: true },
    autoRenderQueue: { current: [] },
    setExportJob: vi.fn(),
    setDraftJob: vi.fn(),
    setBusy: vi.fn(),
    setNotice: vi.fn(),
    setAutoGenerateEnabled: vi.fn(),
    setTab: vi.fn(),
    setDraftCompletionSummary: vi.fn(),
  };
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.resetAllMocks();
  api.exportJobEvents.mockRejectedValue(new Error("stream unavailable"));
  api.aiJobEvents.mockRejectedValue(new Error("stream unavailable"));
  api.project.mockRejectedValueOnce(new ApiError("temporarily unavailable", 503, null, undefined, "http")).mockResolvedValue({ ...structuredClone(fixture), title: "refreshed", revision: 3 });
});
afterEach(() => {
  vi.useRealTimers();
});

it("holds export completion until the project refresh succeeds and preserves the line-update cursor", async () => {
  const state = model();
  const next = { id: "export", status: "completed", message: "done", updateVersion: 2, lineUpdates: [{ version: 2, sceneId: fixture.scenes[0].id, line: fixture.scenes[0].lines[0] }] };
  api.exportJob.mockResolvedValue(next);
  const { unmount } = renderHook(() => useStudioExportMonitor({ ...state, exportJob: { id: "export", status: "generating" } } as unknown as StudioEffectModel));
  await act(() => vi.advanceTimersByTimeAsync(0));
  expect(state.setBusy).not.toHaveBeenCalled();
  expect(state.setExportJob).not.toHaveBeenCalled();
  expect(state.exportUpdateVersion.current).toBe(2);
  await act(() => vi.advanceTimersByTimeAsync(1500));
  expect(api.project).toHaveBeenCalledTimes(2);
  expect(api.exportJob).toHaveBeenLastCalledWith("export", 2);
  expect(state.editSession.savedProject()?.title).toBe("refreshed");
  expect(state.setBusy).toHaveBeenCalledExactlyOnceWith(null);
  expect(state.setExportJob).toHaveBeenCalledExactlyOnceWith(next);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it("does not consume a draft chunk until its project refresh succeeds", async () => {
  const state = model();
  const next = { id: "draft", status: "generating", completedChunks: 1 };
  api.aiJob.mockResolvedValue(next);
  const { unmount } = renderHook(() => useStudioDraftMonitor({ ...state, draftJob: { id: "draft", status: "generating", completedChunks: 0 } } as unknown as StudioEffectModel));
  await act(() => vi.advanceTimersByTimeAsync(0));
  expect(state.setDraftJob).not.toHaveBeenCalled();
  expect(state.setBusy).not.toHaveBeenCalled();
  await act(() => vi.advanceTimersByTimeAsync(1500));
  expect(api.project).toHaveBeenCalledTimes(2);
  expect(state.setDraftJob).toHaveBeenCalledExactlyOnceWith(next);
  expect(state.editSession.savedProject()?.title).toBe("refreshed");
  expect(state.setBusy).not.toHaveBeenCalled();
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it("does not publish progress or project data after the monitored owner changes", async () => {
  const state = model();
  api.exportJob.mockResolvedValue({ id: "export", status: "completed", updateVersion: 0 });
  const { unmount } = renderHook(() => useStudioExportMonitor({ ...state, exportJob: { id: "export", status: "generating" } } as unknown as StudioEffectModel));
  await act(() => vi.advanceTimersByTimeAsync(0));
  act(() => state.editSession.replace({ ...structuredClone(fixture), id: "other" } as StudioProject));
  await act(() => vi.advanceTimersByTimeAsync(1500));
  expect(state.editSession.savedProject()?.id).toBe("other");
  expect(state.setExportJob).not.toHaveBeenCalled();
  expect(state.setBusy).not.toHaveBeenCalled();
  expect(api.project).toHaveBeenCalledOnce();
  expect(api.exportJob).toHaveBeenCalledOnce();
  unmount();
});

it.each(["export", "draft"] as const)("reconciles %s cancellation and releases busy only after refreshing the project", async (kind) => {
  const state = model();
  const next = { id: "job", status: "cancelled", completedChunks: 0, updateVersion: 0 };
  api.exportJob.mockResolvedValue(next);
  api.aiJob.mockResolvedValue(next);
  const view = renderHook(() => {
    useStudioExportMonitor({ ...state, exportJob: kind === "export" ? { ...next, status: "generating" } : null } as unknown as StudioEffectModel);
    useStudioDraftMonitor({ ...state, draftJob: kind === "draft" ? { ...next, status: "generating" } : null } as unknown as StudioEffectModel);
  });
  await act(() => vi.advanceTimersByTimeAsync(0));
  expect(state.setBusy).not.toHaveBeenCalled();
  await act(() => vi.advanceTimersByTimeAsync(1500));
  expect(state.editSession.savedProject()?.title).toBe("refreshed");
  expect(state.setBusy).toHaveBeenCalledExactlyOnceWith(null);
  expect(kind === "export" ? state.setExportJob : state.setDraftJob).toHaveBeenCalledExactlyOnceWith(next);
  expect(state.setNotice).toHaveBeenCalledWith(expect.stringContaining("キャンセルしました"));
  view.unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it.each(["export", "draft"] as const)("keeps %s monitor failures within the captured project", async (kind) => {
  for (const changeProject of [false, true]) {
    const state = model();
    let reject!: (error: Error) => void;
    const request = kind === "export" ? api.exportJob : api.aiJob;
    request.mockImplementation(() => new Promise((_, fail) => (reject = fail)));
    const job = { id: "job", status: "generating", completedChunks: 0 };
    const view = renderHook(() => {
      useStudioExportMonitor({ ...state, exportJob: kind === "export" ? job : null } as unknown as StudioEffectModel);
      useStudioDraftMonitor({ ...state, draftJob: kind === "draft" ? job : null } as unknown as StudioEffectModel);
    });
    await act(() => vi.advanceTimersByTimeAsync(0));
    if (changeProject) state.editSession.replace({ ...structuredClone(fixture), id: "other" } as StudioProject);
    await act(async () => reject(new ApiError("forbidden", 403, null, undefined, "http")));
    if (changeProject) {
      expect(state.setBusy).not.toHaveBeenCalled();
      expect(state.setNotice).not.toHaveBeenCalled();
    } else {
      expect(state.setBusy).toHaveBeenCalledExactlyOnceWith(null);
      expect(state.setNotice).toHaveBeenCalledWith(expect.stringContaining("forbidden"));
    }
    view.unmount();
  }
});
