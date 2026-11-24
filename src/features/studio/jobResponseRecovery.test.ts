import { afterEach, expect, it, vi } from "vitest";
import { request } from "../../api-core";
import { ApiConnectionError } from "../../api-error";
import { monitorJobEvents } from "./jobEventMonitor";

function disconnectedResponse(error: Error) {
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.error(error);
      },
    }),
    { headers: { "Content-Type": "application/json" } },
  );
}
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("classifies a network disconnect after response headers as a connection failure", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(disconnectedResponse(new TypeError("connection closed"))));
  await expect(request("/api/exports/jobs/job")).rejects.toBeInstanceOf(ApiConnectionError);
});

it("recovers job monitoring when the JSON response body is interrupted", async () => {
  vi.useFakeTimers();
  vi.spyOn(console, "error").mockImplementation(() => {});
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(disconnectedResponse(new TypeError("connection closed")))
    .mockResolvedValueOnce(Response.json({ status: "completed" }));
  vi.stubGlobal("fetch", fetch);
  const onSnapshot = vi.fn();
  const monitor = monitorJobEvents({
    jobId: "job",
    signal: new AbortController().signal,
    maxStreamAttempts: 0,
    stream: vi.fn(),
    poll: () => request<{ status: string }>("/api/exports/jobs/job"),
    onSnapshot,
    isTerminal: (job) => job.status === "completed",
    snapshotFromEvent: () => ({ status: "generating" }),
    pollIntervalMs: 1000,
  });
  const outcome = monitor.then(
    () => "completed",
    (error: unknown) => error,
  );
  await vi.advanceTimersByTimeAsync(0);
  expect(onSnapshot).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1000);
  expect(await outcome).toBe("completed");
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(onSnapshot).toHaveBeenCalledExactlyOnceWith({ status: "completed" });
});

it("does not reclassify a deliberately aborted body read", async () => {
  const controller = new AbortController();
  const error = new DOMException("aborted", "AbortError");
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(async () => {
      controller.abort();
      return disconnectedResponse(error);
    }),
  );
  await expect(request("/api/project", { signal: controller.signal })).rejects.toBe(error);
});
