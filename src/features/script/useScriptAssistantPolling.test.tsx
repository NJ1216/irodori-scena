import { useState } from "react";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiConnectionError, ApiError } from "../../api-error";
import type { ScriptAssistantJob } from "./scriptAssistantTypes";
import { useScriptAssistantPolling } from "./useScriptAssistantPolling";

const mocks = vi.hoisted(() => ({ scriptAssistantJob: vi.fn() }));
vi.mock("../../api", () => ({ api: mocks }));
const pending: ScriptAssistantJob = { id: "job", operation: "insert", status: "generating", phase: "dialogue", message: "生成中", overallProgress: 35 };
const completed: ScriptAssistantJob = {
  ...pending,
  status: "completed",
  overallProgress: 100,
  groups: [
    { id: "individual", sceneId: "scene", sceneTitle: "", atomic: false, contiguous: true, rows: [{ id: "usable", text: "使える提案", characterId: "cast", characterName: "", stageDirection: "" }], originalRows: [], warnings: ["一部の行を除外しました"] },
    { id: "cue", sceneId: "scene", sceneTitle: "", atomic: true, contiguous: true, rows: [{ id: "cue-row", text: "同時発話", characterId: "cast", characterName: "", stageDirection: "" }], originalRows: [], warnings: [] },
  ],
};
const httpError = (status: number) => new ApiError("status unavailable", status, null, undefined, "http");
function setup() {
  const onBusy = vi.fn();
  const onNotice = vi.fn();
  const hook = renderHook(() => {
    const [job, setJob] = useState<ScriptAssistantJob | null>(pending);
    const [rows, setAcceptedRows] = useState(new Set<string>());
    const [groups, setAcceptedGroups] = useState(new Set<string>());
    const running = useScriptAssistantPolling({ job, setJob, setAcceptedRows, setAcceptedGroups, onBusy, onNotice });
    return { job, rows, groups, running };
  });
  return { ...hook, onBusy, onNotice };
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.resetAllMocks();
});
afterEach(() => vi.useRealTimers());

it.each([new ApiConnectionError("offline"), httpError(408), httpError(429), httpError(503)])("recovers progress and usable proposals after %s", async (error) => {
  mocks.scriptAssistantJob.mockRejectedValueOnce(error).mockResolvedValue(completed);
  const hook = setup();
  await act(() => vi.advanceTimersByTimeAsync(300));
  expect(hook.result.current.running).toBe(true);
  expect(hook.result.current.job?.overallProgress).toBe(35);
  expect(hook.onBusy).not.toHaveBeenCalled();
  await act(() => vi.advanceTimersByTimeAsync(700));
  expect(hook.result.current.running).toBe(false);
  expect(hook.result.current.job).toEqual(completed);
  expect([...hook.result.current.rows]).toEqual(["usable"]);
  expect([...hook.result.current.groups]).toEqual(["cue"]);
  expect(hook.onBusy).toHaveBeenCalledExactlyOnceWith(null);
  expect(hook.onNotice).toHaveBeenLastCalledWith("通信が回復しました。");
  expect(mocks.scriptAssistantJob).toHaveBeenCalledTimes(2);
  expect(vi.getTimerCount()).toBe(0);
});

it.each([httpError(401), httpError(404), new SyntaxError("invalid JSON")])("exits the progress state after a permanent failure: %s", async (error) => {
  mocks.scriptAssistantJob.mockRejectedValue(error);
  const hook = setup();
  await act(() => vi.advanceTimersByTimeAsync(2000));
  expect(hook.result.current.running).toBe(false);
  expect(hook.onNotice).toHaveBeenCalledWith(expect.stringContaining(error.message));
  expect(hook.onBusy).toHaveBeenCalledExactlyOnceWith(null);
  expect(mocks.scriptAssistantJob).toHaveBeenCalledOnce();
  expect(hook.result.current.rows.size).toBe(0);
  expect(vi.getTimerCount()).toBe(0);
});

it("stops retrying when the owner unmounts", async () => {
  mocks.scriptAssistantJob.mockRejectedValue(new ApiConnectionError("offline"));
  const hook = setup();
  await act(() => vi.advanceTimersByTimeAsync(300));
  hook.unmount();
  await act(() => vi.advanceTimersByTimeAsync(2000));
  expect(mocks.scriptAssistantJob).toHaveBeenCalledOnce();
  expect(vi.getTimerCount()).toBe(0);
});
