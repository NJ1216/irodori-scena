import { describe, expect, it, vi } from "vitest";
import type { ProgressEvent } from "../../types";
import { monitorJobEvents, updatesAfterVersion } from "./jobEventMonitor";

type Snapshot = { id: string; status: string; value: number };
const event = (sequence: number, terminal = false): ProgressEvent => ({
  sequence,
  jobId: "job-1",
  phase: terminal ? "completed" : "working",
  current: sequence,
  total: 3,
  metrics: { status: terminal ? "completed" : "working", value: sequence },
  timestamp: "2026-08-25T00:00:00Z",
  terminal,
});
const fromEvent = (value: ProgressEvent): Snapshot => ({
  id: value.jobId,
  status: String(value.metrics.status),
  value: Number(value.metrics.value),
});

describe("monitorJobEvents stalled connections", () => {
  it.each([false, true])("reconciles an open stream after idle or terminal without waiting for EOF (terminal=%s)", async (terminal) => {
    vi.useFakeTimers();
    try {
      const stream = vi.fn(
        (onEvent, options: { signal?: AbortSignal }) =>
          new Promise<void>((resolve) => {
            options.signal?.addEventListener("abort", () => resolve(), { once: true });
            onEvent(event(1, terminal));
          }),
      );
      const poll = vi.fn().mockResolvedValue({ id: "job-1", status: "completed", value: 9 });
      const onSnapshot = vi.fn();
      const result = monitorJobEvents({
        jobId: "job-1",
        signal: new AbortController().signal,
        stream,
        poll,
        onSnapshot,
        isTerminal: (value: Snapshot) => value.status === "completed",
        snapshotFromEvent: fromEvent,
        pollIntervalMs: 1,
        streamIdleTimeoutMs: 30_000,
      });
      if (!terminal) {
        await vi.advanceTimersByTimeAsync(29_999);
        expect(poll).not.toHaveBeenCalled();
        await vi.advanceTimersByTimeAsync(1);
      }
      await result;
      expect(stream).toHaveBeenCalledOnce();
      expect(poll).toHaveBeenCalledOnce();
      expect(onSnapshot).toHaveBeenLastCalledWith({ id: "job-1", status: "completed", value: 9 });
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("continues monitoring if terminal reconciliation returns a running snapshot", async () => {
    const poll = vi.fn().mockResolvedValueOnce({ id: "job-1", status: "working", value: 2 }).mockResolvedValueOnce({ id: "job-1", status: "completed", value: 3 });
    await monitorJobEvents({
      jobId: "job-1",
      signal: new AbortController().signal,
      stream: async (onEvent) => onEvent(event(1, true)),
      poll,
      onSnapshot: vi.fn(),
      isTerminal: (value: Snapshot) => value.status === "completed",
      snapshotFromEvent: fromEvent,
      pollIntervalMs: 0,
    });
    expect(poll).toHaveBeenCalledTimes(2);
  });
});

describe("monitorJobEvents", () => {
  it("preserves the export update cursor when SSE snapshots replay older lines", () => {
    expect(updatesAfterVersion([{ version: 1 }, { version: 2 }, { version: 3 }], 2)).toEqual([{ version: 3 }]);
  });

  it("deduplicates sequences, reconnects with Last-Event-ID, and confirms terminal state", async () => {
    const snapshots: Snapshot[] = [];
    const stream = vi
      .fn()
      .mockImplementationOnce(async (onEvent) => {
        onEvent(event(1));
        onEvent(event(1));
        throw new Error("closed");
      })
      .mockImplementationOnce(async (onEvent) => {
        onEvent(event(2));
        onEvent(event(3, true));
      });
    const poll = vi.fn().mockResolvedValue({ id: "job-1", status: "completed", value: 4 });
    await monitorJobEvents({
      jobId: "job-1",
      signal: new AbortController().signal,
      stream,
      poll,
      onSnapshot: (value) => {
        snapshots.push(value);
      },
      isTerminal: (value) => value.status === "completed",
      snapshotFromEvent: fromEvent,
      pollIntervalMs: 1,
    });
    expect(stream.mock.calls[1][1]).toMatchObject({ lastEventId: 1 });
    expect(snapshots.map((value) => value.value)).toEqual([1, 2, 4]);
    expect(poll).toHaveBeenCalledOnce();
  });

  it("falls back to polling after bounded stream attempts", async () => {
    const snapshots: Snapshot[] = [];
    const stream = vi.fn().mockRejectedValue(new Error("unavailable"));
    const poll = vi.fn().mockResolvedValueOnce({ id: "job-1", status: "working", value: 1 }).mockResolvedValueOnce({ id: "job-1", status: "completed", value: 2 });
    await monitorJobEvents({
      jobId: "job-1",
      signal: new AbortController().signal,
      stream,
      poll,
      onSnapshot: (value) => {
        snapshots.push(value);
      },
      isTerminal: (value) => value.status === "completed",
      snapshotFromEvent: fromEvent,
      pollIntervalMs: 0,
    });
    expect(stream).toHaveBeenCalledTimes(2);
    expect(poll).toHaveBeenCalledTimes(2);
    expect(snapshots.map((value) => value.status)).toEqual(["working", "completed"]);
  });

  it("keeps SSE off and uses polling when the screening attempt count is zero", async () => {
    const stream = vi.fn();
    const poll = vi.fn().mockResolvedValue({ id: "job-1", status: "completed", value: 1 });
    await monitorJobEvents({
      jobId: "job-1",
      signal: new AbortController().signal,
      stream,
      poll,
      onSnapshot: vi.fn(),
      isTerminal: (value) => value.status === "completed",
      snapshotFromEvent: fromEvent,
      pollIntervalMs: 0,
      maxStreamAttempts: 0,
    });
    expect(stream).not.toHaveBeenCalled();
    expect(poll).toHaveBeenCalledOnce();
  });
});

describe("monitorJobEvents failure handling", () => {
  it("stops applying SSE and immediately reconciles by GET when a sequence is missing", async () => {
    const snapshots: Snapshot[] = [];
    const stream = vi.fn(async (onEvent) => {
      onEvent(event(1));
      onEvent(event(3));
    });
    const poll = vi.fn().mockResolvedValue({ id: "job-1", status: "completed", value: 9 });
    await monitorJobEvents({
      jobId: "job-1",
      signal: new AbortController().signal,
      stream,
      poll,
      onSnapshot: (value) => {
        snapshots.push(value);
      },
      isTerminal: (value) => value.status === "completed",
      snapshotFromEvent: fromEvent,
      pollIntervalMs: 0,
    });
    expect(stream).toHaveBeenCalledOnce();
    expect(snapshots.map((value) => value.value)).toEqual([1, 9]);
  });

  it("falls back to GET when applying an SSE snapshot fails", async () => {
    const applied: number[] = [];
    const stream = vi.fn(async (onEvent) => {
      onEvent(event(1));
    });
    const poll = vi.fn().mockResolvedValue({ id: "job-1", status: "completed", value: 9 });
    await monitorJobEvents({
      jobId: "job-1",
      signal: new AbortController().signal,
      stream,
      poll,
      onSnapshot: (value) => {
        if (value.value === 1) throw new Error("apply failed");
        applied.push(value.value);
      },
      isTerminal: (value) => value.status === "completed",
      snapshotFromEvent: fromEvent,
      pollIntervalMs: 0,
    });
    expect(stream).toHaveBeenCalledOnce();
    expect(applied).toEqual([9]);
  });

  it("aborts a still-open stream before fallback when snapshot application rejects", async () => {
    const stream = vi.fn(
      (onEvent, options: { signal?: AbortSignal }) =>
        new Promise<void>((_resolve, reject) => {
          options.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), {
            once: true,
          });
          onEvent(event(1));
        }),
    );
    const poll = vi.fn().mockResolvedValue({ id: "job-1", status: "completed", value: 9 });
    await monitorJobEvents({
      jobId: "job-1",
      signal: new AbortController().signal,
      stream,
      poll,
      onSnapshot: (value) => {
        if (value.value === 1) return Promise.reject(new Error("apply failed"));
      },
      isTerminal: (value) => value.status === "completed",
      snapshotFromEvent: fromEvent,
      pollIntervalMs: 0,
    });
    expect(stream.mock.calls[0]?.[1].signal?.aborted).toBe(true);
    expect(poll).toHaveBeenCalledOnce();
  });

  it("stops reconnect and polling after abort", async () => {
    const controller = new AbortController();
    const poll = vi.fn();
    const stream = vi.fn(async () => {
      controller.abort();
      throw new DOMException("aborted", "AbortError");
    });
    await monitorJobEvents({
      jobId: "job-1",
      signal: controller.signal,
      stream,
      poll,
      onSnapshot: vi.fn(),
      isTerminal: () => false,
      snapshotFromEvent: fromEvent,
      pollIntervalMs: 1,
    });
    expect(stream).toHaveBeenCalledOnce();
    expect(poll).not.toHaveBeenCalled();
  });
});
