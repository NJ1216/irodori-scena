import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { TtsCatalogItem, TtsInstallJob } from "../../types";
import { useTtsInstallJob } from "./useTtsInstallJob";

const api = vi.hoisted(() => ({ startTtsInstall: vi.fn(), startTtsVariantInstall: vi.fn(), cancelTtsInstall: vi.fn(), ttsInstall: vi.fn() }));
vi.mock("../../api", () => ({ api }));
afterEach(() => {
  vi.useRealTimers();
  vi.resetAllMocks();
});

it("keeps a completed or newer installation when an older cancellation responds", async () => {
  vi.useFakeTimers();
  api.startTtsInstall.mockResolvedValueOnce({ id: "old", state: "running" }).mockResolvedValueOnce({ id: "new", state: "running" });
  api.ttsInstall.mockResolvedValue({ id: "old", state: "complete" });
  let finish!: (job: TtsInstallJob) => void;
  api.cancelTtsInstall.mockImplementation(() => new Promise((resolve) => (finish = resolve)));
  const onInstalled = vi.fn().mockResolvedValue(undefined);
  const hook = renderHook(() => useTtsInstallJob(onInstalled));
  await act(() => hook.result.current.start({ id: "model" } as TtsCatalogItem));
  let cancelled!: Promise<void>;
  act(() => {
    cancelled = hook.result.current.cancel();
  });
  await act(() => vi.advanceTimersByTimeAsync(500));
  expect(hook.result.current.active).toBe(false);
  await act(() => hook.result.current.start({ id: "next" } as TtsCatalogItem));
  await act(async () => {
    finish({ id: "old", state: "cancelling" } as TtsInstallJob);
    await cancelled;
  });
  expect(hook.result.current.job).toEqual({ id: "new", state: "running" });
  expect(onInstalled).toHaveBeenCalledOnce();
  hook.unmount();
});

it("marks pending starts busy and admits only one request across start methods", async () => {
  let finish!: (job: TtsInstallJob) => void;
  api.startTtsInstall.mockImplementation(() => new Promise((resolve) => (finish = resolve)));
  const hook = renderHook(() => useTtsInstallJob(vi.fn()));
  let started!: Promise<void>;
  act(() => {
    started = hook.result.current.start({ id: "model" } as TtsCatalogItem);
    void hook.result.current.startVariant("other", "variant");
  });
  expect(hook.result.current.active).toBe(true);
  expect(api.startTtsInstall).toHaveBeenCalledOnce();
  expect(api.startTtsVariantInstall).not.toHaveBeenCalled();
  await act(async () => {
    finish({ id: "install", state: "running" } as TtsInstallJob);
    await started;
  });
  expect(hook.result.current.job?.id).toBe("install");
  hook.unmount();
});

it("acknowledges cancellation immediately while retaining newer byte progress", async () => {
  vi.useFakeTimers();
  api.startTtsInstall.mockResolvedValue({ id: "install", state: "running", downloadedBytes: 10 });
  api.ttsInstall.mockResolvedValue({ id: "install", state: "running", downloadedBytes: 50 });
  let finish!: (job: TtsInstallJob) => void;
  api.cancelTtsInstall.mockImplementation(() => new Promise((resolve) => (finish = resolve)));
  const hook = renderHook(() => useTtsInstallJob(vi.fn()));
  await act(() => hook.result.current.start({ id: "model" } as TtsCatalogItem));
  let pending!: Promise<void>;
  act(() => {
    pending = hook.result.current.cancel();
  });
  await act(() => vi.advanceTimersByTimeAsync(500));
  await act(async () => {
    finish({ id: "install", state: "cancelling", downloadedBytes: 10 } as TtsInstallJob);
    await pending;
  });
  expect(hook.result.current.job).toEqual({ id: "install", state: "cancelling", downloadedBytes: 50 });
  hook.unmount();
});

it("retries installed-model refresh before marking installation complete", async () => {
  vi.useFakeTimers();
  api.startTtsInstall.mockResolvedValue({ id: "install", state: "running" });
  api.ttsInstall.mockResolvedValue({ id: "install", state: "complete" });
  const onInstalled = vi.fn().mockRejectedValueOnce(new Error("refresh failed")).mockResolvedValue(undefined);
  const hook = renderHook(() => useTtsInstallJob(onInstalled));
  await act(() => hook.result.current.start({ id: "model" } as TtsCatalogItem));
  await act(() => vi.advanceTimersByTimeAsync(500));
  expect(hook.result.current.active).toBe(true);
  await act(() => vi.advanceTimersByTimeAsync(500));
  expect(onInstalled).toHaveBeenCalledTimes(2);
  expect(hook.result.current.job?.state).toBe("complete");
  expect(hook.result.current.error).toBe("");
  hook.unmount();
});
