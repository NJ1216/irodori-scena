import { useState } from "react";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import fixture from "../../../tests/fixtures/project-contract.json";
import type { DraftJob, StudioProject } from "../../types";
import { ProjectEditSession } from "../studio/projectEditSession";
import { useAiDirectionProgress } from "./useAiDirectionProgress";

const api = vi.hoisted(() => ({ aiJob: vi.fn(), project: vi.fn() }));
vi.mock("../../api", () => ({ api }));
const terminalJob = (status = "completed") => ({ id: "direction", status, performanceCompletedLines: 1, renderLineIds: [fixture.scenes[0].lines[0].id] }) as DraftJob;
function setup() {
  const projectSession = new ProjectEditSession(vi.fn());
  projectSession.replace(structuredClone(fixture) as StudioProject);
  const operation = { current: projectSession.capture() };
  const callbacks = { onComplete: vi.fn(), onClose: vi.fn(), onNotice: vi.fn() };
  const hook = renderHook(() => {
    const [job, setJob] = useState({ ...terminalJob(), status: "generating" } as DraftJob);
    useAiDirectionProgress({ ...callbacks, projectSession, operation, job, setJob, running: job.status === "generating", takeMode: "append" });
    return job;
  });
  return { ...hook, ...callbacks, projectSession, operation };
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.resetAllMocks();
});
afterEach(() => vi.useRealTimers());

it.each(["completed", "failed"])("retries final project loading before accepting a %s result", async (status) => {
  api.aiJob.mockResolvedValue(terminalJob(status));
  api.project.mockRejectedValueOnce(new Error("offline")).mockResolvedValue(fixture);
  const hook = setup();
  await act(() => vi.advanceTimersByTimeAsync(0));
  expect(hook.result.current.status).toBe("generating");
  expect(hook.onComplete).not.toHaveBeenCalled();
  await act(() => vi.advanceTimersByTimeAsync(1000));
  expect(api.project).toHaveBeenCalledTimes(2);
  expect(hook.onComplete).toHaveBeenCalledExactlyOnceWith(fixture, terminalJob().renderLineIds, "append", hook.operation.current);
  expect(hook.result.current.status).toBe(status);
  expect(hook.onClose).toHaveBeenCalledTimes(status === "completed" ? 1 : 0);
  hook.unmount();
});

it.each(["switch", "unmount"])("discards final refresh side effects after %s", async (change) => {
  let resolve!: (project: StudioProject) => void;
  api.aiJob.mockResolvedValue(terminalJob());
  api.project.mockImplementation(() => new Promise((done) => (resolve = done)));
  const hook = setup();
  await act(() => vi.advanceTimersByTimeAsync(0));
  if (change === "unmount") hook.unmount();
  else act(() => hook.projectSession.replace({ ...fixture, id: "other" } as StudioProject));
  await act(async () => resolve(fixture as StudioProject));
  expect(hook.onComplete).not.toHaveBeenCalled();
  expect(hook.onNotice).not.toHaveBeenCalled();
  expect(hook.onClose).not.toHaveBeenCalled();
  hook.unmount();
});
