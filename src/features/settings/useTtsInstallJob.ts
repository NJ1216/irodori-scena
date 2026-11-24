import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api";
import type { TtsCatalogItem, TtsInstallJob } from "../../types";
import { useSequentialPolling } from "../shared/useSequentialPolling";

const ACTIVE_STATES: TtsInstallJob["state"][] = ["queued", "running", "cancelling"];

export function recommendedTtsModel(models: TtsCatalogItem[]) {
  return models.filter((item) => item.legacy === false && item.installable === true).sort((a, b) => (a.recommendedOrder ?? Number.MAX_SAFE_INTEGER) - (b.recommendedOrder ?? Number.MAX_SAFE_INTEGER))[0] ?? null;
}

export function useTtsInstallJob(onInstalled: () => Promise<void>) {
  const [job, setJob] = useState<TtsInstallJob | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const pendingStart = useRef(false);
  const currentJob = useRef<TtsInstallJob | null>(null);
  const acceptJob = useCallback((next: TtsInstallJob | null) => {
    currentJob.current = next;
    setJob(next);
  }, []);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const active = starting || (!!job && ACTIVE_STATES.includes(job.state));
  useSequentialPolling({
    enabled: active && !starting && !!job,
    intervalMs: 500,
    initialDelayMs: 500,
    poll: () => api.ttsInstall(job!.id),
    terminal: (next) => !ACTIVE_STATES.includes(next.state),
    onResult: async (next, signal) => {
      if (next.state === "complete") await onInstalled();
      if (signal.aborted) return;
      acceptJob(next);
      setError("");
    },
    onError: (reason) => setError((reason as Error).message),
  });
  const startJob = useCallback(
    async (request: () => Promise<TtsInstallJob>) => {
      if (pendingStart.current || (currentJob.current && ACTIVE_STATES.includes(currentJob.current.state))) return;
      pendingStart.current = true;
      setStarting(true);
      acceptJob(null);
      try {
        setError("");
        const next = await request();
        if (mounted.current) acceptJob(next);
      } catch (reason) {
        if (mounted.current) setError((reason as Error).message);
      } finally {
        pendingStart.current = false;
        if (mounted.current) setStarting(false);
      }
    },
    [acceptJob],
  );
  const start = useCallback((item: TtsCatalogItem) => startJob(() => api.startTtsInstall("model", item.id)), [startJob]);
  const startVariant = useCallback((modelId: string, variantId: string) => startJob(() => api.startTtsVariantInstall(modelId, variantId)), [startJob]);
  const cancel = useCallback(async () => {
    if (!job || !["queued", "running"].includes(job.state)) return;
    try {
      await api.cancelTtsInstall(job.id);
      const latest = currentJob.current;
      if (mounted.current && latest?.id === job.id && ACTIVE_STATES.includes(latest.state)) acceptJob({ ...latest, state: "cancelling" });
    } catch (reason) {
      if (mounted.current && currentJob.current?.id === job.id && ACTIVE_STATES.includes(currentJob.current.state)) setError((reason as Error).message);
    }
  }, [job, acceptJob]);
  return { job, error, active, start, startVariant, cancel };
}
