// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TimelinePlaybackAudio } from "./timelinePlaybackAudio";
import type { TimelineInterval } from "./timelineApi";
const mocks = vi.hoisted(() => ({ clock: { currentTime: 0 }, sources: [] as Array<{ start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn>; buffer?: unknown; onended?: () => void }>, active: vi.fn(), fetch: vi.fn(), decode: vi.fn() }));
vi.mock("../../api-runtime", () => ({ apiFetch: mocks.fetch }));
vi.mock("../shared/audioEngine", () => ({
  audioEngine: {
    createBufferSource: vi.fn(async () => {
      const source = { start: vi.fn(), stop: vi.fn(), disconnect: vi.fn() };
      mocks.sources.push(source);
      return { context: mocks.clock, source };
    }),
    decodeAudioData: mocks.decode,
    setBufferPlaybackActive: mocks.active,
  },
}));
function interval(start: number, status: TimelineInterval["status"] = "ready"): TimelineInterval {
  return {
    intervalId: `${start}`,
    planId: "p",
    generation: 1,
    startFrame: start,
    endFrame: start + 1000,
    sampleRate: 1000,
    status,
    audioUrl: "/part.wav",
    dependencyLineIds: [],
    events: [
      { lineId: "a", startFrame: 0, endFrame: 500 },
      { lineId: "b", startFrame: 250, endFrame: 1700 },
    ],
  };
}
beforeEach(() => {
  mocks.clock.currentTime = 0;
  mocks.sources.length = 0;
  mocks.active.mockReset();
  mocks.fetch.mockReset().mockResolvedValue({ ok: true, arrayBuffer: async () => new ArrayBuffer(2) });
  mocks.decode.mockReset().mockResolvedValue({ context: mocks.clock, buffer: { duration: 1 } });
});
describe("timeline audio clock", () => {
  it("reserves ready consecutive chunks exactly once and balances meter ownership", async () => {
    const audio = new TimelinePlaybackAudio();
    const signal = new AbortController().signal;
    for (const start of [0, 1000]) {
      await audio.prepare(interval(start), signal);
      await audio.schedule(interval(start));
    }
    expect(mocks.sources.map((source) => source.start.mock.calls[0][0])).toEqual([0.02, 1.02]);
    expect(mocks.active.mock.calls).toEqual([[true]]);
    mocks.clock.currentTime = 0.4;
    expect(audio.activeIds()).toEqual(["b", "a"]);
    mocks.clock.currentTime = 0.8;
    expect(audio.activeIds()).toEqual(["b"]);
    audio.close();
    audio.close();
    expect(mocks.active.mock.calls).toEqual([[true], [false]]);
    expect(mocks.sources.every((source) => source.stop.mock.calls.length === 1)).toBe(true);
  });
  it("does not reserve unready audio and resumes the same frame after a silent wait", async () => {
    const audio = new TimelinePlaybackAudio();
    const signal = new AbortController().signal;
    expect(await audio.schedule(interval(0, "waiting-input"))).toBe(false);
    expect(mocks.sources).toHaveLength(0);
    await audio.prepare(interval(0), signal);
    await audio.schedule(interval(0));
    mocks.clock.currentTime = 4;
    expect(audio.activeIds()).toEqual([]);
    await audio.prepare(interval(1000), signal);
    await audio.schedule(interval(1000));
    expect(mocks.sources.at(-1)!.start).toHaveBeenCalledWith(4.02);
    audio.close();
  });
  it("preserves already decoded buffers when the input URL changes", async () => {
    const audio = new TimelinePlaybackAudio();
    const signal = new AbortController().signal;
    const original = interval(0);
    await audio.prepare(original, signal);
    const captured = { ...original, audioUrl: "/new.wav" };
    await audio.prepare(captured, signal);
    await audio.schedule(original);
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
    expect(mocks.sources[0].buffer).toEqual({ duration: 1 });
    audio.close();
  });
  it("distinguishes known silence from an unfinished chunk", async () => {
    const audio = new TimelinePlaybackAudio();
    expect(await audio.schedule({ ...interval(0, "silence"), events: [] })).toBe(true);
    expect(mocks.sources[0].start).not.toHaveBeenCalled();
    expect(audio.aheadSeconds()).toBe(1.02);
    audio.close();
  });
});
