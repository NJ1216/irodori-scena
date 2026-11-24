import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useSequentialPolling } from "./useSequentialPolling";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it("retries a terminal result until its asynchronous application succeeds", async () => {
  vi.useFakeTimers();
  const poll = vi.fn().mockResolvedValue("done");
  const onResult = vi.fn().mockRejectedValueOnce(new Error("refresh failed")).mockResolvedValue(undefined);
  const onError = vi.fn();
  const hook = renderHook(() => useSequentialPolling({ enabled: true, intervalMs: 100, poll, onResult, onError, terminal: (value) => value === "done" }));
  await act(() => vi.advanceTimersByTimeAsync(0));
  await act(() => vi.advanceTimersByTimeAsync(500));
  expect(onError).toHaveBeenCalledOnce();
  expect(poll).toHaveBeenCalledTimes(2);
  expect(onResult).toHaveBeenCalledTimes(2);
  expect(vi.getTimerCount()).toBe(0);
  hook.unmount();
});

describe("useSequentialPolling", () => {
  it("never overlaps requests and handles a terminal result once", async () => {
    vi.useFakeTimers();
    let resolveFirst!: (value: string) => void;
    const poll = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<string>((resolve) => {
            resolveFirst = resolve;
          }),
      )
      .mockResolvedValue("done");
    const onResult = vi.fn();
    renderHook(() => useSequentialPolling({ enabled: true, intervalMs: 100, poll, onResult, terminal: (value) => value === "done" }));

    await act(() => vi.advanceTimersByTimeAsync(0));
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(poll).toHaveBeenCalledOnce();
    await act(async () => resolveFirst("working"));
    await act(() => vi.advanceTimersByTimeAsync(100));
    expect(poll).toHaveBeenCalledTimes(2);
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(onResult).toHaveBeenCalledTimes(2);
    expect(poll).toHaveBeenCalledTimes(2);
  });

  it("does not publish after unmount", async () => {
    vi.useFakeTimers();
    let resolve!: (value: string) => void;
    const onResult = vi.fn();
    const hook = renderHook(() =>
      useSequentialPolling({
        enabled: true,
        intervalMs: 10,
        poll: () =>
          new Promise<string>((done) => {
            resolve = done;
          }),
        onResult,
      }),
    );
    await act(() => vi.advanceTimersByTimeAsync(0));
    hook.unmount();
    await act(async () => resolve("late"));
    expect(onResult).not.toHaveBeenCalled();
  });

  it("pauses while hidden and resumes immediately", async () => {
    vi.useFakeTimers();
    let visibility = "hidden";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility as DocumentVisibilityState);
    const poll = vi.fn().mockResolvedValue("working");
    renderHook(() => useSequentialPolling({ enabled: true, intervalMs: 100, poll, onResult: vi.fn() }));
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(poll).not.toHaveBeenCalled();
    visibility = "visible";
    document.dispatchEvent(new Event("visibilitychange"));
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(poll).toHaveBeenCalledOnce();
  });

  it.each(["request", "result"] as const)("keeps one polling chain when visibility changes during the %s", async (pending) => {
    vi.useFakeTimers();
    let visibility: DocumentVisibilityState = "visible";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const poll = vi
      .fn()
      .mockImplementationOnce(async () => {
        if (pending === "request") await gate;
        return "working";
      })
      .mockResolvedValue("done");
    const onResult = vi.fn(async (value: string) => {
      if (pending === "result" && value === "working") await gate;
    });
    renderHook(() => useSequentialPolling({ enabled: true, intervalMs: 100, poll, onResult, terminal: (value) => value === "done" }));
    await act(() => vi.advanceTimersByTimeAsync(0));

    visibility = "hidden";
    document.dispatchEvent(new Event("visibilitychange"));
    visibility = "visible";
    document.dispatchEvent(new Event("visibilitychange"));
    document.dispatchEvent(new Event("visibilitychange"));
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(poll).toHaveBeenCalledOnce();

    await act(async () => release());
    await act(() => vi.advanceTimersByTimeAsync(100));
    await act(() => vi.advanceTimersByTimeAsync(500));
    expect(onResult.mock.calls.map(([value]) => value)).toEqual(["working", "done"]);
    expect(poll).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("replaces the pending timer on repeated visible notifications", async () => {
    vi.useFakeTimers();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    const poll = vi.fn().mockResolvedValue("working");
    renderHook(() => useSequentialPolling({ enabled: true, intervalMs: 100, poll, onResult: vi.fn() }));
    document.dispatchEvent(new Event("visibilitychange"));
    document.dispatchEvent(new Event("visibilitychange"));
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(poll).toHaveBeenCalledOnce();
    await act(() => vi.advanceTimersByTimeAsync(100));
    expect(poll).toHaveBeenCalledTimes(2);
  });

  it.each(["retry", "stop"] as const)("uses the %s error policy", async (errorPolicy) => {
    vi.useFakeTimers();
    const poll = vi.fn().mockRejectedValue(new Error("offline"));
    const onError = vi.fn();
    renderHook(() => useSequentialPolling({ enabled: true, intervalMs: 100, poll, onResult: vi.fn(), onError, errorPolicy }));
    await act(() => vi.advanceTimersByTimeAsync(0));
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(onError).toHaveBeenCalledTimes(errorPolicy === "retry" ? 4 : 1);
  });
});
