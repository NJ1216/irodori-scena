import type { ProgressEvent } from "../../types";
import { ApiConnectionError, ApiError } from "../../api-error";

type StreamOptions = { signal?: AbortSignal; lastEventId?: number };

export type JobEventMonitorOptions<T> = {
  jobId: string;
  signal: AbortSignal;
  stream: (onEvent: (event: ProgressEvent) => void, options: StreamOptions) => Promise<void>;
  poll: () => Promise<T>;
  onSnapshot: (snapshot: T) => void | Promise<void>;
  isTerminal: (snapshot: T) => boolean;
  snapshotFromEvent: (event: ProgressEvent) => T;
  pollIntervalMs: number;
  maxStreamAttempts?: number;
  streamIdleTimeoutMs?: number;
};

const terminalJobStatuses = new Set(["completed", "completed_with_warnings", "failed", "cancelled"]);

export function isTerminalJobStatus(status: string) {
  return terminalJobStatuses.has(status);
}

export function isTerminalJob(job: { status: string }) {
  return isTerminalJobStatus(job.status);
}

/** Progress events carry the job snapshot fields in `metrics`. */
export function snapshotFromProgressEvent<T>(event: ProgressEvent): T {
  return { ...event.metrics, id: event.jobId, phase: event.phase } as unknown as T;
}

export function updatesAfterVersion<T extends { version: number }>(updates: T[] | undefined, version: number): T[] {
  return (updates ?? []).filter((update) => update.version > version);
}

function abortableDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve();
    const timer = window.setTimeout(finish, milliseconds);
    function finish() {
      window.clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      resolve();
    }
    signal.addEventListener("abort", finish, { once: true });
  });
}

async function consumeEventStream<T>(options: JobEventMonitorOptions<T>, lastSequence: number): Promise<{ lastSequence: number; terminal: boolean; fallback: boolean; aborted: boolean }> {
  let sequence = lastSequence;
  let terminal = false;
  let fallback = false;
  let processing = Promise.resolve();
  const connection = new AbortController();
  const abortConnection = () => connection.abort();
  const idleTimeout = options.streamIdleTimeoutMs ?? 30_000;
  const expireStream = () => {
    fallback = true;
    connection.abort();
  };
  let idleTimer = window.setTimeout(expireStream, idleTimeout);
  options.signal.addEventListener("abort", abortConnection, { once: true });
  try {
    await options.stream(
      (event) => {
        if (connection.signal.aborted) return;
        if (event.jobId !== options.jobId || event.sequence <= sequence) return;
        window.clearTimeout(idleTimer);
        idleTimer = window.setTimeout(expireStream, idleTimeout);
        if (event.sequence !== sequence + 1) {
          fallback = true;
          connection.abort();
          throw new Error("進捗イベントの欠落を検出しました。");
        }
        sequence = event.sequence;
        terminal = event.terminal || options.isTerminal(options.snapshotFromEvent(event));
        if (terminal) {
          connection.abort();
          return;
        }
        processing = processing
          .then(() => options.onSnapshot(options.snapshotFromEvent(event)))
          .catch(() => {
            fallback = true;
            connection.abort();
          });
      },
      { signal: connection.signal, lastEventId: sequence || undefined },
    );
  } catch {
    if (options.signal.aborted) {
      return { lastSequence: sequence, terminal, fallback, aborted: true };
    }
  } finally {
    window.clearTimeout(idleTimer);
    options.signal.removeEventListener("abort", abortConnection);
  }
  await processing;
  return { lastSequence: sequence, terminal, fallback, aborted: false };
}

function retryableProgressFailure(error: unknown) {
  return error instanceof ApiConnectionError || (error instanceof ApiError && ([408, 429].includes(error.status) || (error.status >= 500 && error.status < 600)));
}

/** Prefer authenticated SSE, then fall back to the established GET polling path. */
export async function monitorJobEvents<T>(options: JobEventMonitorOptions<T>): Promise<void> {
  const attempts = Math.max(0, options.maxStreamAttempts ?? 2);
  let lastSequence = 0;
  let terminal = false;

  for (let attempt = 0; attempt < attempts && !options.signal.aborted && !terminal; attempt += 1) {
    const result = await consumeEventStream(options, lastSequence);
    if (result.aborted) return;
    lastSequence = result.lastSequence;
    terminal = result.terminal;
    if (result.fallback) break;
  }
  // Terminal events also reconcile through GET; transport failures must not
  // turn a completed event into a permanently unobserved job.
  let pollingDelay = Math.max(0, options.pollIntervalMs);
  const initialRetryDelay = Math.min(5000, Math.max(250, options.pollIntervalMs));
  let retryDelay = initialRetryDelay;
  while (!options.signal.aborted) {
    try {
      const snapshot = await options.poll();
      if (options.signal.aborted) return;
      await options.onSnapshot(snapshot);
      if (options.isTerminal(snapshot)) return;
      retryDelay = initialRetryDelay;
    } catch (error) {
      if (options.signal.aborted) return;
      if (!retryableProgressFailure(error)) throw error;
      await abortableDelay(retryDelay, options.signal);
      retryDelay = Math.min(5000, retryDelay * 2);
      continue;
    }
    await abortableDelay(pollingDelay, options.signal);
    pollingDelay = Math.min(5000, Math.max(options.pollIntervalMs, pollingDelay * 2));
  }
}
