import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "../../api-error";
import { serviceConnectionFailure } from "../../api-failure";
import type { ProgressEvent } from "../../types";
import { monitorJobEvents } from "./jobEventMonitor";

type Snapshot = { status: string; updateVersion: number };
const done: Snapshot = { status: "completed", updateVersion: 2 };
const terminalEvent: ProgressEvent = { jobId: "job", sequence: 1, phase: "completed", current: 2, total: 2, metrics: done, terminal: true, timestamp: "" };
const httpError = (status: number) => new ApiError("request failed", status, null, undefined, "http");
function options(controller = new AbortController()) {
  return {
    jobId: "job",
    signal: controller.signal,
    stream: vi.fn(async () => {
      throw new Error("SSE unavailable");
    }),
    poll: vi.fn<() => Promise<Snapshot>>().mockResolvedValue(done),
    onSnapshot: vi.fn<(value: Snapshot) => Promise<void>>().mockResolvedValue(),
    snapshotFromEvent: (event: ProgressEvent) => event.metrics as Snapshot,
    isTerminal: (snapshot: Snapshot) => snapshot.status === "completed",
    pollIntervalMs: 1000,
  };
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it.each([false, true])("recovers from a transport failure and reconciles completion (terminal SSE=%s)", async (terminal) => {
  const configuration = options();
  configuration.poll.mockRejectedValueOnce(serviceConnectionFailure(new TypeError("network failed")));
  const monitor = monitorJobEvents({ ...configuration, stream: terminal ? async (receive) => receive(terminalEvent) : configuration.stream });
  const settled = vi.fn();
  const finished = monitor.then(settled);
  await vi.advanceTimersByTimeAsync(0);
  expect(configuration.poll).toHaveBeenCalledOnce();
  expect(configuration.onSnapshot).not.toHaveBeenCalled();
  expect(settled).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1000);
  await finished;
  expect(configuration.poll).toHaveBeenCalledTimes(2);
  expect(configuration.onSnapshot).toHaveBeenCalledExactlyOnceWith(done);
  expect(vi.getTimerCount()).toBe(0);
});

it("backs off retryable HTTP failures and preserves the last applied cursor", async () => {
  const configuration = options();
  let cursor = 0;
  const cursors: number[] = [];
  configuration.poll.mockResolvedValueOnce({ status: "generating", updateVersion: 1 }).mockRejectedValueOnce(httpError(503)).mockRejectedValueOnce(httpError(429));
  const monitor = monitorJobEvents({
    ...configuration,
    poll: () => {
      cursors.push(cursor);
      return configuration.poll();
    },
    onSnapshot: async (snapshot) => {
      cursor = snapshot.updateVersion;
      await configuration.onSnapshot(snapshot);
    },
  });
  await vi.advanceTimersByTimeAsync(2999);
  expect(cursors).toEqual([0, 1, 1]);
  expect(cursor).toBe(1);
  await vi.advanceTimersByTimeAsync(1001);
  await monitor;
  expect(cursors).toEqual([0, 1, 1, 1]);
  expect(cursor).toBe(2);
});

it("retries a failed project refresh without treating the job as completed", async () => {
  const configuration = options();
  configuration.onSnapshot.mockRejectedValueOnce(httpError(503));
  const settled = vi.fn();
  const monitor = monitorJobEvents(configuration).then(settled);
  await vi.advanceTimersByTimeAsync(0);
  expect(settled).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1000);
  await monitor;
  expect(configuration.onSnapshot).toHaveBeenCalledTimes(2);
});

it.each([401, 403, 404, 410, 422])("does not retry permanent HTTP %s", async (status) => {
  const configuration = options();
  const error = httpError(status);
  configuration.poll.mockRejectedValueOnce(error);
  await expect(monitorJobEvents(configuration)).rejects.toBe(error);
  expect(configuration.poll).toHaveBeenCalledOnce();
  expect(vi.getTimerCount()).toBe(0);
});

it("does not hide an application failure while applying a snapshot", async () => {
  const configuration = options();
  const error = new TypeError("invalid project data");
  configuration.onSnapshot.mockRejectedValueOnce(error);
  await expect(monitorJobEvents(configuration)).rejects.toBe(error);
  expect(configuration.poll).toHaveBeenCalledOnce();
});

it("aborts during backoff without another request", async () => {
  const controller = new AbortController();
  const configuration = options(controller);
  configuration.poll.mockRejectedValueOnce(httpError(503));
  const monitor = monitorJobEvents(configuration);
  await vi.advanceTimersByTimeAsync(0);
  controller.abort();
  await monitor;
  await vi.advanceTimersByTimeAsync(60_000);
  expect(configuration.poll).toHaveBeenCalledOnce();
  expect(vi.getTimerCount()).toBe(0);
});
