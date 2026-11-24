import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearPlaybackRenderDiagnostics, playbackRenderDiagnostics, recordPlaybackRenderEvent, summarizePlaybackRenderDiagnostics, type PlaybackRenderEvent } from "./playbackRenderDiagnostics";

describe("playback and automatic-render diagnostics", () => {
  beforeEach(() => {
    clearPlaybackRenderDiagnostics();
    vi.restoreAllMocks();
  });

  it("keeps a shared monotonic event timeline without project content", () => {
    vi.spyOn(performance, "now").mockReturnValueOnce(10).mockReturnValueOnce(25);
    recordPlaybackRenderEvent({ kind: "auto-render-started", lineId: "line-1" });
    recordPlaybackRenderEvent({ kind: "playback-window-announced", playbackId: "playback-1", detail: { boundaryCount: 2 } });

    expect(playbackRenderDiagnostics()).toEqual([
      { atMs: 10, kind: "auto-render-started", lineId: "line-1", detail: undefined },
      { atMs: 25, kind: "playback-window-announced", playbackId: "playback-1", detail: { boundaryCount: 2 } },
    ]);
  });

  it("summarizes the measurement statistics and fallback count", () => {
    const source: PlaybackRenderEvent[] = [10, 20, 30, 40].map((durationMs, index) => ({ atMs: index, kind: "auto-render-completed", durationMs }));
    source.push({ atMs: 5, kind: "playback-overlap-fallback", playbackId: "playback-1" }, { atMs: 6, kind: "playback-finished", playbackId: "playback-1" }, { atMs: 7, kind: "playback-cancelled", playbackId: "playback-2" });
    const summary = summarizePlaybackRenderDiagnostics(source);

    expect(summary.autoRender).toEqual({ count: 4, minMs: 10, medianMs: 30, p95Ms: 40, maxMs: 40 });
    expect(summary.completedCount).toBe(4);
    expect(summary.fallbackCount).toBe(1);
    expect(summary.playbackCount).toBe(2);
    expect(summary.finishedPlaybackCount).toBe(1);
    expect(summary.cancelledPlaybackCount).toBe(1);
  });

  it("pairs an interruption with only the next start of the same queued row", () => {
    const source: PlaybackRenderEvent[] = [
      { atMs: 10, kind: "auto-render-started", lineId: "line-1" },
      { atMs: 30, kind: "auto-render-interrupted", lineId: "line-1", durationMs: 20 },
      { atMs: 35, kind: "auto-render-started", lineId: "line-2" },
      { atMs: 80, kind: "auto-render-started", lineId: "line-1" },
    ];

    expect(summarizePlaybackRenderDiagnostics(source).requeueRestart).toEqual({ count: 1, minMs: 50, medianMs: 50, p95Ms: 50, maxMs: 50 });
  });
});
