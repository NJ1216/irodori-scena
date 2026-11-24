import { act, renderHook } from "@testing-library/react";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { useLoraAudition } from "./useLoraAudition";
const mocks = vi.hoisted(() => ({ request: vi.fn(), play: vi.fn(), stop: vi.fn(), setSource: vi.fn(async () => true), dispose: vi.fn(), seek: vi.fn(), callbacks: vi.fn() }));
vi.mock("../../api-core", () => ({ request: mocks.request }));
vi.mock("../shared/decodedAudioPlayer", () => ({
  DecodedAudioPlayer: class {
    setCallbacks = mocks.callbacks;
    seek = mocks.seek;
    play = mocks.play;
    stop = mocks.stop;
    setSource = mocks.setSource;
    dispose = mocks.dispose;
  },
}));
const props = {
  character: { id: "cast", referenceAudioUrl: "ref", referenceVersion: 2, sampleText: "台詞" },
  mix: { version: 1, baseWeight: 10000, entries: [] },
  project: { id: "project", settings: { quality: "fast", steps: 16, speechRate: 1.2, textCfg: 3, voiceCfg: 5 }, ttsSelection: {} },
  onPlay: vi.fn(),
} as unknown as Parameters<typeof useLoraAudition>[0];
beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});
it("captures unsaved mix and click settings, caches audio and stops on input change", async () => {
  mocks.request.mockResolvedValue({ id: "job", status: "completed", audioUrl: "/audio" });
  const { result, rerender, unmount } = renderHook((value) => useLoraAudition(value), { initialProps: props });
  await act(async () => {
    await result.current.toggle();
  });
  const sent = JSON.parse(mocks.request.mock.calls[0][1].body);
  expect(sent.loraMix).toEqual(props.mix);
  expect(sent.referenceVersion).toBe(2);
  expect(sent.settings.captionCfg).toBe(3);
  expect(sent.settings.speechRate).toBe(1);
  await act(async () => {
    await result.current.toggle();
  });
  expect(mocks.request).toHaveBeenCalledTimes(1);
  expect(mocks.play).toHaveBeenCalledTimes(2);
  rerender({ ...props, mix: { ...props.mix, entries: [] }, character: { ...props.character, referenceVersion: 3 } });
  expect(mocks.stop).toHaveBeenCalled();
  await act(async () => {
    await result.current.toggle();
  });
  expect(mocks.request.mock.calls.filter(([url]) => url === "/api/lora/previews")).toHaveLength(2);
  unmount();
  expect(mocks.dispose).toHaveBeenCalled();
});
it("late start response after edit is cancelled without playback", async () => {
  let release!: (job: unknown) => void;
  mocks.request.mockImplementation((path) =>
    path === "/api/lora/previews"
      ? new Promise((resolve) => {
          release = resolve;
        })
      : Promise.resolve({ id: "old", status: "cancelled" }),
  );
  const { result, rerender } = renderHook((value) => useLoraAudition(value), { initialProps: props });
  let operation!: Promise<void>;
  act(() => {
    operation = result.current.toggle();
  });
  rerender({ ...props, character: { ...props.character, id: "other" } });
  await act(async () => {
    release({ id: "old", status: "completed", audioUrl: "/audio" });
    await operation;
  });
  expect(mocks.play).not.toHaveBeenCalled();
  expect(mocks.request).toHaveBeenCalledWith("/api/lora/previews/old/cancel", { method: "POST" });
});
it("cancel during polling ignores completed response and retains draft", async () => {
  mocks.request.mockResolvedValue({ id: "job", status: "generating" });
  const { result } = renderHook(() => useLoraAudition(props));
  let operation!: Promise<void>;
  await act(async () => {
    operation = result.current.toggle();
    await Promise.resolve();
  });
  expect(result.current.generating).toBe(true);
  await act(async () => {
    await result.current.toggle();
    await vi.advanceTimersByTimeAsync(350);
    await operation;
  });
  expect(result.current.generating).toBe(false);
  expect(mocks.play).not.toHaveBeenCalled();
  expect(props.mix.baseWeight).toBe(10000);
});
it("reports generation error and does not replace the draft", async () => {
  mocks.request.mockResolvedValue({ id: "bad", status: "failed", error: "missing reference" });
  const { result } = renderHook(() => useLoraAudition(props));
  await act(async () => {
    await result.current.toggle();
  });
  expect(result.current.error).toBe("missing reference");
  expect(mocks.play).not.toHaveBeenCalled();
});

it("exposes playback time and seeking, and clears the timeline when the mix changes", async () => {
  const { result, rerender } = renderHook((value) => useLoraAudition(value), { initialProps: props });
  const callbacks = mocks.callbacks.mock.calls.at(-1)![0];
  act(() => {
    callbacks.onDuration(12.5);
    callbacks.onTime(3.25);
  });
  expect(result.current.duration).toBe(12.5);
  expect(result.current.currentTime).toBe(3.25);
  act(() => result.current.seek(7));
  expect(mocks.seek).toHaveBeenCalledWith(7);
  rerender({ ...props, character: { ...props.character, referenceVersion: 4 } });
  expect(mocks.setSource).toHaveBeenLastCalledWith("");
});

it("ignores project speech-rate changes without cancelling or regenerating the cached preview", async () => {
  mocks.request.mockResolvedValue({ id: "job", status: "completed", audioUrl: "/audio" });
  const { result, rerender } = renderHook((value) => useLoraAudition(value), { initialProps: props });
  await act(async () => {
    await result.current.toggle();
  });
  mocks.setSource.mockClear();
  rerender({ ...props, project: { ...props.project, settings: { ...props.project.settings, speechRate: 2 } } });
  expect(mocks.setSource).not.toHaveBeenCalled();
  await act(async () => {
    await result.current.toggle();
  });
  expect(mocks.request).toHaveBeenCalledTimes(1);
  expect(mocks.play).toHaveBeenCalledTimes(2);
  expect(props.project.settings.speechRate).toBe(1.2);
});
