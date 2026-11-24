export type PlaybackRenderEvent = {
  atMs: number;
  kind: string;
  playbackId?: string;
  lineId?: string;
  boundary?: number;
  durationMs?: number;
  detail?: Record<string, number | string | boolean | null>;
};

// A long negative-GAP script can produce a few hundred events per pass. Keep
// enough in-memory history for the prescribed 30 alternating measurement runs.
const MAX_EVENTS = 20_000;
const events: PlaybackRenderEvent[] = [];

export function recordPlaybackRenderEvent(event: Omit<PlaybackRenderEvent, "atMs">) {
  if (!import.meta.env.DEV) return;
  events.push({ atMs: performance.now(), ...event });
  if (events.length > MAX_EVENTS) events.splice(0, events.length - MAX_EVENTS);
}

export function playbackRenderDiagnostics() {
  return events.map((event) => ({ ...event, detail: event.detail ? { ...event.detail } : undefined }));
}

export function clearPlaybackRenderDiagnostics() {
  events.length = 0;
}

function percentile(values: number[], fraction: number) {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.ceil((sorted.length - 1) * fraction)];
}

function requeueRestartDurations(source: PlaybackRenderEvent[]) {
  const startsByLine = new Map<string, PlaybackRenderEvent[]>();
  source.forEach((event) => {
    if (event.kind !== "auto-render-started" || !event.lineId) return;
    const starts = startsByLine.get(event.lineId) ?? [];
    starts.push(event);
    startsByLine.set(event.lineId, starts);
  });
  return source.flatMap((event) => {
    if (event.kind !== "auto-render-interrupted" || !event.lineId) return [];
    const restart = startsByLine.get(event.lineId)?.find((candidate) => candidate.atMs > event.atMs);
    return restart ? [restart.atMs - event.atMs] : [];
  });
}

export function summarizePlaybackRenderDiagnostics(source = events) {
  const durations = (kind: string) => source.filter((event) => event.kind === kind && event.durationMs !== undefined).map((event) => event.durationMs as number);
  const summary = (values: number[]) => ({ count: values.length, minMs: percentile(values, 0), medianMs: percentile(values, 0.5), p95Ms: percentile(values, 0.95), maxMs: percentile(values, 1) });
  const playbackIds = new Set(source.flatMap((event) => (event.playbackId ? [event.playbackId] : [])));
  return {
    autoRender: summary(durations("auto-render-completed")),
    interrupted: summary(durations("auto-render-interrupted")),
    cancellation: summary(durations("auto-render-worker-stopped")),
    requeueRestart: summary(requeueRestartDurations(source)),
    overlapReady: summary(durations("playback-overlap-ready")),
    completedCount: source.filter((event) => event.kind === "auto-render-completed").length,
    interruptedCount: source.filter((event) => event.kind === "auto-render-interrupted").length,
    fallbackCount: source.filter((event) => event.kind === "playback-overlap-fallback").length,
    playbackCount: playbackIds.size,
    finishedPlaybackCount: source.filter((event) => event.kind === "playback-finished").length,
    cancelledPlaybackCount: source.filter((event) => event.kind === "playback-cancelled").length,
  };
}

declare global {
  interface Window {
    __SCENA_PLAYBACK_RENDER_DIAGNOSTICS__?: {
      read: typeof playbackRenderDiagnostics;
      clear: typeof clearPlaybackRenderDiagnostics;
      summarize: typeof summarizePlaybackRenderDiagnostics;
    };
  }
}

if (import.meta.env.DEV && typeof window !== "undefined") {
  window.__SCENA_PLAYBACK_RENDER_DIAGNOSTICS__ = {
    read: playbackRenderDiagnostics,
    clear: clearPlaybackRenderDiagnostics,
    summarize: summarizePlaybackRenderDiagnostics,
  };
}
