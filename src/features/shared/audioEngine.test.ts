import { afterEach, describe, expect, it, vi } from "vitest";
import { AudioEngine, dbToGain, MASTER_VOLUME_KEY, restoreMasterVolume, rmsDb, samplePeakDb } from "./audioEngine";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function audioContext(state: AudioContextState | "interrupted" = "running") {
  const node = () => ({ connect: vi.fn(), channelCount: 0, channelCountMode: "max", channelInterpretation: "speakers", gain: { value: 0 } });
  return {
    state,
    destination: {},
    decodeAudioData: vi.fn().mockResolvedValue({ duration: 2 }),
    close: vi.fn().mockResolvedValue(undefined),
    resume: vi.fn(async function (this: { state: string }) {
      this.state = "running";
    }),
    createGain: vi.fn(node),
    createChannelSplitter: vi.fn(node),
    createChannelMerger: vi.fn(node),
    createAnalyser: vi.fn(() => ({ ...node(), fftSize: 0, getFloatTimeDomainData: vi.fn() })),
    createBufferSource: vi.fn(() => ({ connect: vi.fn() })),
  };
}

describe("shared audio engine values", () => {
  it("maps master decibels to linear gain including silence", () => {
    expect(dbToGain(0)).toBe(1);
    expect(dbToGain(6)).toBeCloseTo(1.995, 3);
    expect(dbToGain(-20)).toBeCloseTo(0.1);
    expect(dbToGain(null)).toBe(0);
  });

  it("restores finite values and silence while rejecting invalid storage", () => {
    const storage = (value: string | null) => ({ getItem: (key: string) => (key === MASTER_VOLUME_KEY ? value : null) });
    expect(restoreMasterVolume(storage(null))).toBe(0);
    expect(restoreMasterVolume(storage("-Infinity"))).toBeNull();
    expect(restoreMasterVolume(storage("-18"))).toBe(-18);
    expect(restoreMasterVolume(storage("3"))).toBe(3);
    expect(restoreMasterVolume(storage("7"))).toBe(0);
    expect(restoreMasterVolume(storage("invalid"))).toBe(0);
  });

  it("calculates RMS in the visible -60 to +6 dBFS range", () => {
    expect(rmsDb(new Float32Array([1, -1]))).toBe(0);
    expect(rmsDb(new Float32Array([0.1, -0.1]))).toBeCloseTo(-20);
    expect(rmsDb(new Float32Array([0, 0]))).toBe(-60);
    expect(rmsDb(new Float32Array([2, -2]))).toBe(6);
  });

  it("detects a clipped sample peak independently from RMS", () => {
    const samples = new Float32Array([1.25, -0.25, 0.25, -0.25]);
    expect(rmsDb(samples)).toBeLessThan(0);
    expect(samplePeakDb(samples)).toBeGreaterThan(0);
  });

  it("resumes WebKit interrupted contexts before creating a source", async () => {
    const context = audioContext("interrupted");
    const factory = vi.fn(function AudioContextMock() {
      return context;
    });
    vi.stubGlobal("AudioContext", factory);
    const engine = new AudioEngine();

    await engine.createBufferSource();

    expect(context.resume).toHaveBeenCalledOnce();
    expect(context.createBufferSource).toHaveBeenCalledOnce();
  });

  it("recreates the WebKit output graph after a playback session becomes idle", async () => {
    vi.useFakeTimers();
    const first = audioContext();
    const second = audioContext();
    const contexts = [first, second];
    const factory = vi.fn(function AudioContextMock() {
      return contexts.shift();
    });
    vi.stubGlobal("AudioContext", factory);
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn(() => 1),
    );
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const engine = new AudioEngine();

    await engine.createBufferSource();
    engine.setBufferPlaybackActive(true);
    engine.setBufferPlaybackActive(false);
    await vi.runAllTimersAsync();
    await engine.createBufferSource();

    expect(first.close).toHaveBeenCalledOnce();
    expect(factory).toHaveBeenCalledTimes(2);
  });

  it("keeps the current graph when playback restarts before idle retirement", async () => {
    vi.useFakeTimers();
    const context = audioContext();
    const factory = vi.fn(function AudioContextMock() {
      return context;
    });
    vi.stubGlobal("AudioContext", factory);
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn(() => 1),
    );
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const engine = new AudioEngine();

    await engine.createBufferSource();
    engine.setBufferPlaybackActive(true);
    engine.setBufferPlaybackActive(false);
    await engine.createBufferSource();
    engine.setBufferPlaybackActive(true);
    await vi.runAllTimersAsync();

    expect(context.close).not.toHaveBeenCalled();
    expect(factory).toHaveBeenCalledOnce();
  });
});

it("retires a predecode-only context and recreates output for the cached sample", async () => {
  vi.useFakeTimers();
  const first = audioContext(),
    second = audioContext();
  const contexts = [first, second];
  vi.stubGlobal(
    "AudioContext",
    vi.fn(function () {
      return contexts.shift();
    }),
  );
  const engine = new AudioEngine();
  const decoded = await engine.decodeAudioData(new ArrayBuffer(1));
  await vi.runAllTimersAsync();
  expect(first.close).toHaveBeenCalledOnce();
  const routed = await engine.createBufferSource();
  expect(routed.context).toBe(second);
  expect(decoded.buffer).toEqual({ duration: 2 });
});
it("does not retire output during a pending decode or active playback", async () => {
  vi.useFakeTimers();
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn(() => 1),
  );
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  const context = audioContext();
  let finish!: (buffer: { duration: number }) => void;
  context.decodeAudioData.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  vi.stubGlobal(
    "AudioContext",
    vi.fn(function () {
      return context;
    }),
  );
  const engine = new AudioEngine();
  await engine.createBufferSource();
  const decoding = engine.decodeAudioData(new ArrayBuffer(1));
  await Promise.resolve();
  await vi.runAllTimersAsync();
  expect(context.close).not.toHaveBeenCalled();
  finish({ duration: 2 });
  await decoding;
  engine.setBufferPlaybackActive(true);
  await vi.runAllTimersAsync();
  expect(context.close).not.toHaveBeenCalled();
  engine.setBufferPlaybackActive(false);
  await vi.runAllTimersAsync();
  expect(context.close).toHaveBeenCalledOnce();
});
it("retires output even after predecode failure", async () => {
  vi.useFakeTimers();
  const context = audioContext();
  context.decodeAudioData.mockRejectedValueOnce(new Error("invalid audio"));
  vi.stubGlobal(
    "AudioContext",
    vi.fn(function () {
      return context;
    }),
  );
  const engine = new AudioEngine();
  await expect(engine.decodeAudioData(new ArrayBuffer(1))).rejects.toThrow("invalid audio");
  await vi.runAllTimersAsync();
  expect(context.close).toHaveBeenCalledOnce();
});
