import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useLoraJobMonitor } from "./useLoraJobMonitor";

const { api } = vi.hoisted(() => ({ api: { status: vi.fn(), jobs: vi.fn() } }));
vi.mock("../../api-lora", () => ({ loraApi: api }));
const idle = { id: "j", name: "n", status: "complete" };
const running = { id: "j", name: "n", status: "running" };
beforeEach(() => {
  vi.useFakeTimers();
  vi.resetAllMocks();
  api.status.mockImplementation(async () => ({ supported: true }));
});
afterEach(() => vi.useRealTimers());
// React flushes effects at the end of each act, so advance in small steps like a real clock.
async function tick(ms: number) {
  for (let elapsed = 0; elapsed < ms; elapsed += 100) await act(() => vi.advanceTimersByTimeAsync(100));
}

it("slows polling while no job is running and speeds up when one starts", async () => {
  api.jobs.mockResolvedValue([idle]);
  const hook = renderHook(() => useLoraJobMonitor(vi.fn()));
  await tick(6000);
  expect(api.jobs).toHaveBeenCalledOnce();
  api.jobs.mockResolvedValue([running]);
  act(() => hook.result.current.setJobs([running]));
  await tick(3200);
  expect(api.jobs.mock.calls.length).toBeGreaterThanOrEqual(3);
  api.jobs.mockResolvedValue([idle]);
  await tick(2000);
  const calls = api.jobs.mock.calls.length;
  await tick(6000);
  expect(api.jobs).toHaveBeenCalledTimes(calls);
});

it("does not re-render when polled data is unchanged", async () => {
  api.jobs.mockResolvedValue([running]);
  let renders = 0;
  renderHook(() => {
    renders += 1;
    return useLoraJobMonitor(vi.fn());
  });
  await tick(1600);
  const after = renders;
  await tick(6000);
  expect(api.jobs.mock.calls.length).toBeGreaterThan(3);
  expect(renders).toBe(after);
});

it("reports a failure streak once and again after recovery", async () => {
  const onError = vi.fn();
  api.jobs.mockRejectedValue(new Error("down"));
  renderHook(() => useLoraJobMonitor(onError));
  await tick(30_000);
  expect(onError).toHaveBeenCalledOnce();
  api.jobs.mockResolvedValue([idle]);
  await tick(10_100);
  api.jobs.mockRejectedValue(new Error("down again"));
  await tick(10_100);
  expect(onError).toHaveBeenCalledTimes(2);
});
