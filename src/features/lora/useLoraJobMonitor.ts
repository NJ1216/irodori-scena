import { useEffect, useRef, useState } from "react";
import { loraApi } from "../../api-lora";
import type { LoraJob, LoraStatus } from "../../types/lora";

export function useLoraJobMonitor(onError: (message: string) => void) {
  const [status, setStatus] = useState<LoraStatus | null>(null);
  const [jobs, setJobs] = useState<LoraJob[]>([]);
  const mutationVersion = useRef(0);
  useEffect(() => {
    let alive = true;
    let refreshing = false;
    const refresh = async () => {
      if (refreshing) return;
      refreshing = true;
      const version = mutationVersion.current;
      try {
        const [nextStatus, nextJobs] = await Promise.all([loraApi.status(), loraApi.jobs()]);
        if (alive) {
          setStatus(nextStatus);
          if (version === mutationVersion.current) setJobs(nextJobs);
        }
      } catch (cause) {
        if (alive) onError(String(cause));
      } finally {
        refreshing = false;
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1500);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [onError]);
  return { status, jobs, setJobs, mutationVersion };
}
