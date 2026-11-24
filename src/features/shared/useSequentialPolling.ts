import { useEffect, useRef } from "react";

type Options<T> = {
  enabled: boolean;
  intervalMs: number;
  poll: () => Promise<T>;
  onResult: (value: T, signal: AbortSignal) => void | Promise<void>;
  onError?: (error: unknown) => void;
  errorPolicy?: "retry" | "stop" | ((error: unknown) => "retry" | "stop");
  terminal?: (value: T) => boolean;
  initialDelayMs?: number;
};

/** Runs at most one request at a time and pauses new work while the page is hidden. */
export function useSequentialPolling<T>(options: Options<T>) {
  const latest = useRef(options);
  useEffect(() => {
    latest.current = options;
  });
  useEffect(() => {
    if (!options.enabled) return;
    const controller = new AbortController();
    let stopped = false;
    let finished = false;
    let inFlight = false;
    let timer: number | undefined;
    const schedule = (delay: number) => {
      window.clearTimeout(timer);
      if (!stopped && !finished && !inFlight && document.visibilityState !== "hidden") timer = window.setTimeout(() => void run(), delay);
    };
    const run = async () => {
      if (stopped || finished || inFlight || document.visibilityState === "hidden") return;
      inFlight = true;
      try {
        const value = await latest.current.poll();
        if (stopped) return;
        const terminal = latest.current.terminal?.(value) ?? false;
        await latest.current.onResult(value, controller.signal);
        finished = terminal;
      } catch (error) {
        if (!stopped) {
          latest.current.onError?.(error);
          const policy = latest.current.errorPolicy;
          if ((typeof policy === "function" ? policy(error) : policy) === "stop") finished = true;
        }
      } finally {
        inFlight = false;
        schedule(latest.current.intervalMs);
      }
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") window.clearTimeout(timer);
      else schedule(0);
    };
    document.addEventListener("visibilitychange", onVisibility);
    schedule(options.initialDelayMs ?? 0);
    return () => {
      stopped = true;
      controller.abort();
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [options.enabled, options.intervalMs, options.initialDelayMs]);
}
