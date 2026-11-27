// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useStudioPlayback } from "./useStudioPlayback";

const mocks = vi.hoisted(() => ({ players: [] as Array<{ callbacks?: { onEnded?: () => void; onError?: () => void }; play: ReturnType<typeof vi.fn>; setSource: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> }>, startContinuousPlayback: vi.fn() }));
vi.mock("./continuousPlaybackRunner", () => ({
  createContinuousPlayback: () => mocks.startContinuousPlayback,
  createSelectedPlayback: vi.fn(),
}));
vi.mock("../shared/decodedAudioPlayer", () => ({
  DecodedAudioPlayer: class {
    callbacks?: { onEnded?: () => void; onError?: () => void };
    play = vi.fn();
    setSource = vi.fn().mockResolvedValue(true);
    stop = vi.fn();
    constructor() {
      mocks.players.push(this);
    }
    setCallbacks(callbacks: { onEnded?: () => void; onError?: () => void }) {
      this.callbacks = callbacks;
    }
  },
}));

describe("useStudioPlayback", () => {
  beforeEach(() => {
    mocks.players.length = 0;
    mocks.startContinuousPlayback.mockReset();
  });

  it("plays an unbound reference URL through decoded playback", async () => {
    const model = {
      continuousPlayback: false,
      isProjectPersistencePending: () => false,
      waitForProjectPersistence: vi.fn(),
      setStatusNotice: vi.fn(),
      busy: null,
      stopPlayback: { current: false },
      activeAudio: { current: null },
      resolveActivePlayback: { current: null },
      playbackRun: { current: 0 },
      continuousPlaybackWaiters: { current: new Set() },
      setContinuousPlayback: vi.fn(),
      setFocusedLineId: vi.fn(),
      playingLineId: null,
      setPlayingLineId: vi.fn(),
      playingReferenceCharacterId: null,
      setPlayingReferenceCharacterId: vi.fn(),
      selectedLinePlaybackStopRun: { current: 0 },
      selectedLinePlaybackPending: { current: false },
      stopRef: { current: vi.fn() },
    } as never;
    const { result } = renderHook(() => useStudioPlayback(model));

    act(() => result.current.play("/media/cast-reference.wav"));
    await vi.waitFor(() => expect(mocks.players.at(-1)?.play).toHaveBeenCalledOnce());

    expect(mocks.players.at(-1)?.setSource).toHaveBeenCalledWith("/media/cast-reference.wav");
  });

  it("starts continuous playback only after pending project persistence finishes", async () => {
    let finishPersistence: ((saved: boolean) => void) | undefined;
    const retryFailedSave = vi.fn(
      () =>
        new Promise<boolean>((resolve) => {
          finishPersistence = resolve;
        }),
    );
    const setStatusNotice = vi.fn();
    const model = {
      continuousPlayback: false,
      isProjectPersistencePending: () => true,
      editSession: { retryFailedSave },
      setStatusNotice,
      busy: null,
      stopPlayback: { current: false },
      activeAudio: { current: null },
      resolveActivePlayback: { current: null },
      playbackRun: { current: 0 },
      continuousPlaybackWaiters: { current: new Set() },
      setContinuousPlayback: vi.fn(),
      setFocusedLineId: vi.fn(),
      playingLineId: null,
      setPlayingLineId: vi.fn(),
      playingReferenceCharacterId: null,
      setPlayingReferenceCharacterId: vi.fn(),
      selectedLinePlaybackStopRun: { current: 0 },
      selectedLinePlaybackPending: { current: false },
      stopRef: { current: vi.fn() },
    } as never;
    const { result } = renderHook(() => useStudioPlayback(model));

    let playback: Promise<void> | undefined;
    act(() => {
      playback = result.current.playContinuous();
    });
    expect(setStatusNotice).toHaveBeenCalledWith("変更を保存しています。完了後に連続再生を開始します。");
    expect(mocks.startContinuousPlayback).not.toHaveBeenCalled();

    finishPersistence?.(true);
    await act(async () => {
      await playback;
    });
    expect(mocks.startContinuousPlayback).toHaveBeenCalledOnce();
  });

  it("abandons generated-preview playback without cancelling generation when continuous playback starts", async () => {
    const selectedLinePlaybackStopRun = { current: 3 };
    const selectedLinePlaybackPending = { current: true };
    const stopActiveAudio = vi.fn();
    const playbackRun = { current: 7 };
    const model = {
      continuousPlayback: false,
      isProjectPersistencePending: () => false,
      editSession: { retryFailedSave: vi.fn().mockResolvedValue(true) },
      setStatusNotice: vi.fn(),
      busy: "generate-selected-lines",
      stopPlayback: { current: false },
      activeAudio: { current: { stop: stopActiveAudio } },
      resolveActivePlayback: { current: vi.fn() },
      playbackRun,
      continuousPlaybackWaiters: { current: new Set() },
      setContinuousPlayback: vi.fn(),
      setFocusedLineId: vi.fn(),
      playingLineId: "line-1",
      setPlayingLineId: vi.fn(),
      playingReferenceCharacterId: null,
      setPlayingReferenceCharacterId: vi.fn(),
      selectedLinePlaybackStopRun,
      selectedLinePlaybackPending,
      stopRef: { current: vi.fn() },
    } as never;
    const { result } = renderHook(() => useStudioPlayback(model));

    await act(async () => {
      await result.current.playContinuous();
    });

    expect(selectedLinePlaybackStopRun.current).toBe(4);
    expect(selectedLinePlaybackPending.current).toBe(false);
    expect(stopActiveAudio).toHaveBeenCalledOnce();
    expect(playbackRun.current).toBe(8);
    expect(mocks.startContinuousPlayback).toHaveBeenCalledOnce();
  });
});

it("toggles a cast reference and clears its state when playback ends", async () => {
  mocks.players.length = 0;
  const model = {
    continuousPlayback: false,
    isProjectPersistencePending: () => false,
    waitForProjectPersistence: vi.fn(),
    setStatusNotice: vi.fn(),
    busy: null,
    stopPlayback: { current: false },
    activeAudio: { current: null },
    resolveActivePlayback: { current: null },
    playbackRun: { current: 0 },
    continuousPlaybackWaiters: { current: new Set() },
    setContinuousPlayback: vi.fn(),
    setFocusedLineId: vi.fn(),
    playingLineId: null,
    setPlayingLineId: vi.fn(),
    playingReferenceCharacterId: null as string | null,
    setPlayingReferenceCharacterId: vi.fn(),
    selectedLinePlaybackStopRun: { current: 0 },
    selectedLinePlaybackPending: { current: false },
    stopRef: { current: vi.fn() },
  };
  const { result, rerender } = renderHook(() => useStudioPlayback(model as never));
  const character = { id: "cast-a", referenceAudioUrl: "/media/cast-reference.wav", referenceVersion: 2 } as never;

  act(() => result.current.playReference(character));
  await vi.waitFor(() => expect(mocks.players.at(-1)?.play).toHaveBeenCalledOnce());
  expect(mocks.players.at(-1)?.setSource).toHaveBeenCalledWith("/media/cast-reference.wav?v=2");
  expect(model.setPlayingReferenceCharacterId).toHaveBeenLastCalledWith("cast-a");

  model.playingReferenceCharacterId = "cast-a";
  rerender();
  const first = mocks.players.at(-1)!;
  act(() => result.current.playReference(character));
  expect(first.stop).toHaveBeenCalled();
  expect(mocks.players).toHaveLength(1);
  expect(model.setPlayingReferenceCharacterId).toHaveBeenLastCalledWith(null);

  model.playingReferenceCharacterId = null;
  rerender();
  act(() => result.current.playReference(character));
  const second = mocks.players.at(-1)!;
  act(() => second.callbacks?.onEnded?.());
  expect(model.setPlayingReferenceCharacterId).toHaveBeenLastCalledWith(expect.any(Function));
  const clear = model.setPlayingReferenceCharacterId.mock.lastCall?.[0];
  expect(clear("cast-a")).toBeNull();
});

describe("continuous playback after a failed save", () => {
  const playbackModel = (retryFailedSave: () => Promise<boolean>, setStatusNotice = vi.fn()) =>
    ({
      continuousPlayback: false,
      isProjectPersistencePending: () => false,
      editSession: { retryFailedSave, persistence: { failureReason: () => "network down" } },
      setStatusNotice,
      busy: null,
      stopPlayback: { current: false },
      activeAudio: { current: null },
      resolveActivePlayback: { current: null },
      playbackRun: { current: 0 },
      continuousPlaybackWaiters: { current: new Set() },
      setContinuousPlayback: vi.fn(),
      setFocusedLineId: vi.fn(),
      playingLineId: null,
      setPlayingLineId: vi.fn(),
      playingReferenceCharacterId: null,
      setPlayingReferenceCharacterId: vi.fn(),
      selectedLinePlaybackStopRun: { current: 0 },
      selectedLinePlaybackPending: { current: false },
      stopRef: { current: vi.fn() },
    }) as never;
  beforeEach(() => mocks.startContinuousPlayback.mockReset());

  it("re-saves silently and then starts playback", async () => {
    const retryFailedSave = vi.fn().mockResolvedValue(true);
    const setStatusNotice = vi.fn();
    const { result } = renderHook(() => useStudioPlayback(playbackModel(retryFailedSave, setStatusNotice)));
    await act(async () => {
      await result.current.playContinuous();
    });
    expect(retryFailedSave).toHaveBeenCalledOnce();
    expect(mocks.startContinuousPlayback).toHaveBeenCalledOnce();
    expect(setStatusNotice).not.toHaveBeenCalled();
  });

  it("keeps playback blocked and shows the failure reason when the re-save fails", async () => {
    const retryFailedSave = vi.fn().mockResolvedValue(false);
    const setStatusNotice = vi.fn();
    const { result } = renderHook(() => useStudioPlayback(playbackModel(retryFailedSave, setStatusNotice)));
    await act(async () => {
      await result.current.playContinuous();
    });
    expect(mocks.startContinuousPlayback).not.toHaveBeenCalled();
    expect(setStatusNotice).toHaveBeenLastCalledWith("network down");
  });
});
