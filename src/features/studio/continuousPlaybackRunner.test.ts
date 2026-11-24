// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StudioProject } from "../../types";
import type { PlaybackModel } from "./useStudioPlayback";
import { createContinuousPlayback, createSelectedPlayback } from "./continuousPlaybackRunner";
import type { TimelineInterval, TimelinePlan } from "./timelineApi";

const mocks = vi.hoisted(() => ({ plan: vi.fn(), prepare: vi.fn(), scheduled: [] as TimelineInterval[], ahead: 0, close: vi.fn() }));
vi.mock("./timelineApi", () => ({ createTimelineLease: () => ({ client_id: "client", playback_id: "playback", sequence: 1 }), timelineApi: { plan: mocks.plan, prepare: mocks.prepare, stop: vi.fn().mockResolvedValue({}) } }));
vi.mock("./timelinePlaybackAudio", () => ({
  TimelinePlaybackAudio: class {
    prepare = vi.fn().mockResolvedValue(undefined);
    schedule = vi.fn(async (interval: TimelineInterval) => {
      mocks.scheduled.push(interval);
      return true;
    });
    aheadSeconds = () => mocks.ahead;
    activeIds = () => ["b", "c"];
    close = mocks.close;
  },
}));

function plan(): TimelinePlan {
  return {
    planId: "p1",
    projectId: "project",
    generation: 1,
    sampleRate: 1000,
    endFrame: 2000,
    resolved: true,
    units: [
      { id: "a", start: 0, duration: 1000, resolved: true, startResolved: true, dependencies: [], members: [{ id: "a", offset: 0, duration: 1000, takeId: "ta", signature: "a" }] },
      { id: "b", start: 1000, duration: 1000, resolved: true, startResolved: true, dependencies: [], members: [{ id: "b", offset: 0, duration: 1000, takeId: "tb", signature: "b" }] },
    ],
  };
}
function interval(start = 0, status: TimelineInterval["status"] = "ready", dependencies: string[] = []): TimelineInterval {
  return { intervalId: `i${start}`, planId: "p1", generation: 1, startFrame: start, endFrame: start + 1000, sampleRate: 1000, status, audioUrl: "/audio.wav", dependencyLineIds: dependencies, events: [{ lineId: start ? "b" : "a", startFrame: start, endFrame: start + 1000 }] };
}
function model(): PlaybackModel {
  const project = { id: "project", scenes: [{ id: "scene", title: "Scene", lines: ["a", "b"].map((id) => ({ id, characterId: "cast", text: id, stageDirection: "", takes: [] })) }], settings: { lineGap: 0.7 } } as unknown as StudioProject;
  return {
    project,
    projectRef: { current: project },
    busyRef: { current: null },
    autoGenerateEnabledRef: { current: false },
    setNotice: vi.fn(),
    setStatusNotice: vi.fn(),
    busy: null,
    stopPlayback: { current: false },
    activeAudio: { current: null },
    resolveActivePlayback: { current: null },
    playbackRun: { current: 0 },
    continuousPlaybackWaiters: { current: new Set() },
    setContinuousPlayback: vi.fn(),
    continuousPlayback: false,
    setFocusedLineId: vi.fn(),
    focusedLineId: null,
    playingLineId: null,
    setPlayingLineId: vi.fn(),
    playingReferenceCharacterId: null,
    setPlayingReferenceCharacterId: vi.fn(),
    selectedLinePlaybackStopRun: { current: 0 },
    selectedLinePlaybackPending: { current: false },
    stopRef: { current: vi.fn() },
    runWithAutoRenderPriorityRef: { current: vi.fn((action) => action()) },
    isProjectPersistencePending: () => false,
    waitForProjectPersistence: vi.fn().mockResolvedValue(true),
  };
}
function stop(value: PlaybackModel) {
  value.stopPlayback.current = true;
  value.resolveActivePlayback.current?.();
}
async function tick() {
  await vi.advanceTimersByTimeAsync(110);
}

beforeEach(() => {
  vi.useFakeTimers();
  mocks.scheduled.length = 0;
  mocks.ahead = 0;
  mocks.plan.mockReset().mockResolvedValue(plan());
  mocks.prepare.mockReset();
  mocks.close.mockClear();
  mocks.prepare.mockImplementation(async (_plan, start) => ({ status: "ok", plan: plan(), intervals: [interval(start)] }));
});
afterEach(() => {
  vi.useRealTimers();
});

describe("continuous interval playback", () => {
  it("starts a ready positive/zero-gap introduction without waiting for later missing WAVs", async () => {
    const value = model();
    mocks.prepare.mockImplementation(async (_plan, start) => ({ status: "ok", plan: plan(), intervals: [interval(start, start ? "waiting-input" : "ready", start ? ["b"] : [])] }));
    const run = createContinuousPlayback(value)();
    await tick();
    expect(mocks.scheduled.map((item) => item.startFrame)).toEqual([0]);
    expect(value.setContinuousPlayback).not.toHaveBeenCalledWith(false);
    expect(value.autoGenerateEnabledRef.current).toBe(false);
    stop(value);
    await run;
  });
  it("prepares the next two intervals without suspending automatic TTS for playback", async () => {
    const value = model();
    await createContinuousPlayback(value)();
    expect(mocks.prepare.mock.calls.map((call) => call[1])).toEqual([0, 1000]);
    expect(value.runWithAutoRenderPriorityRef.current).not.toHaveBeenCalled();
  });
  it("waits and resumes at exactly the same frame without a zero-gap substitution", async () => {
    const value = model();
    mocks.prepare.mockResolvedValueOnce({ status: "ok", plan: plan(), intervals: [interval(0, "rendering")] });
    const run = createContinuousPlayback(value)();
    await tick();
    await run;
    expect(mocks.prepare.mock.calls.map((call) => call[1])).toEqual([0, 0, 1000]);
    expect(mocks.scheduled.map((item) => item.startFrame)).toEqual([0, 1000]);
  });
  it("promotes all missing interval dependencies, including far numbered lines", async () => {
    const value = model();
    value.autoGenerateEnabledRef.current = true;
    const queued = { current: [] };
    const process = vi.fn().mockResolvedValue(undefined);
    Object.assign(value, { autoRenderQueue: queued, processAutoRenderQueueRef: { current: process } });
    mocks.prepare.mockResolvedValue({ status: "ok", plan: plan(), intervals: [interval(0, "waiting-input", ["a", "b"])] });
    const run = createContinuousPlayback(value)();
    await tick();
    expect(queued.current).toEqual(expect.arrayContaining([expect.objectContaining({ lineId: "a", cause: "playback-required", mode: "append" }), expect.objectContaining({ lineId: "b", cause: "playback-required" })]));
    stop(value);
    await run;
  });
  it("keeps the session enabled while several missing cue members become ready", async () => {
    const value = model();
    mocks.prepare.mockResolvedValueOnce({ status: "ok", plan: plan(), intervals: [interval(0, "waiting-input", ["a", "b"])] });
    mocks.prepare.mockResolvedValueOnce({ status: "ok", plan: plan(), intervals: [interval(0, "waiting-input", ["b"])] });
    const run = createContinuousPlayback(value)();
    await tick();
    expect(mocks.scheduled).toHaveLength(0);
    expect(value.setContinuousPlayback).not.toHaveBeenCalledWith(false);
    await tick();
    await run;
    expect(mocks.scheduled).toHaveLength(2);
  });
  it("uses the requested onset for middle playback and keeps later-numbered earlier voices", async () => {
    const value = model();
    value.focusedLineId = "b";
    await createContinuousPlayback(value)();
    expect(mocks.prepare.mock.calls[0][1]).toBe(1000);
    expect(mocks.prepare.mock.calls[0][2]).toEqual(["b"]);
  });
  it("adopts appended future lines after a plan change", async () => {
    const value = model();
    const next = plan();
    next.planId = "p2";
    next.units.push({ ...next.units[1], id: "c", start: 1000, members: [{ ...next.units[1].members[0], id: "c" }] });
    mocks.prepare.mockResolvedValueOnce({ status: "ok", plan: plan(), intervals: [interval()] });
    mocks.prepare.mockResolvedValueOnce({ status: "stale", plan: next, intervals: [] });
    await createContinuousPlayback(value)();
    expect(mocks.prepare.mock.calls[2][2]).toContain("c");
  });
  it("does not insert moved/new speech into already reserved time", async () => {
    const value = model();
    const next = plan();
    next.planId = "p2";
    next.units[1].start = 0;
    mocks.prepare.mockResolvedValueOnce({ status: "ok", plan: plan(), intervals: [interval()] });
    mocks.prepare.mockResolvedValueOnce({ status: "stale", plan: next, intervals: [] });
    await createContinuousPlayback(value)();
    expect(mocks.scheduled.map((item) => item.startFrame)).toEqual([0]);
    expect(mocks.prepare).toHaveBeenCalledTimes(2);
  });
  it("ignores delayed completion after stop or generation replacement", async () => {
    const value = model();
    let finish!: (value: unknown) => void;
    mocks.prepare.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const run = createContinuousPlayback(value)();
    await tick();
    value.playbackRun.current += 1;
    finish({ status: "ok", plan: plan(), intervals: [interval()] });
    await run;
    expect(mocks.scheduled).toEqual([]);
    expect(value.setContinuousPlayback).not.toHaveBeenCalledWith(false);
  });
  it("shows actual active member IDs and accepts stop while waiting", async () => {
    const value = model();
    mocks.prepare.mockResolvedValue({ status: "ok", plan: plan(), intervals: [interval(0, "waiting-input", ["a"])] });
    const run = createContinuousPlayback(value)();
    await tick();
    expect(value.setPlayingLineId).toHaveBeenCalledWith("b|c");
    stop(value);
    await run;
    expect(mocks.close).toHaveBeenCalled();
  });
});

it("finishes selected playback without waiting for excluded missing audio", async () => {
  const value = model();
  const selection = plan();
  selection.resolved = false;
  selection.units[1].members[0].duration = null;
  mocks.plan.mockResolvedValue(selection);
  await createSelectedPlayback(value, ["a"])();
  expect(mocks.prepare).toHaveBeenCalledTimes(1);
  expect(mocks.prepare.mock.calls[0][2]).toEqual(["a"]);
});

it("anchors selected playback in script order rather than selection click order", async () => {
  const value = model();
  await createSelectedPlayback(value, ["b", "a"])();
  expect(mocks.prepare.mock.calls[0][1]).toBe(0);
  expect(mocks.prepare.mock.calls[0][2]).toEqual(["a", "b"]);
});
