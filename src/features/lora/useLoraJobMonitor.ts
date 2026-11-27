import { useRef, useState } from "react";
import { loraApi } from "../../api-lora";
import type { LoraJob, LoraStatus } from "../../types/lora";
import { useSequentialPolling } from "../shared/useSequentialPolling";
import { runningJob } from "./loraDraft";

const RUNNING_POLL_MS = 1500;
const IDLE_POLL_MS = 10_000;
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** Polls every 1.5 s while a job runs and every 10 s otherwise (to notice jobs started elsewhere); setJobs after a start switches back. */
export function useLoraJobMonitor(onError: (message: string) => void) {
  const [status, setStatus] = useState<LoraStatus | null>(null);
  const [jobs, setJobs] = useState<LoraJob[]>([]);
  const mutationVersion = useRef(0);
  const failing = useRef(false);
  useSequentialPolling({
    enabled: true,
    intervalMs: jobs.some((job) => runningJob(job.status)) ? RUNNING_POLL_MS : IDLE_POLL_MS,
    poll: async () => {
      const version = mutationVersion.current;
      const [nextStatus, nextJobs] = await Promise.all([loraApi.status(), loraApi.jobs()]);
      return { nextStatus, nextJobs, version };
    },
    onResult: ({ nextStatus, nextJobs, version }) => {
      failing.current = false;
      setStatus((current) => (same(current, nextStatus) ? current : nextStatus));
      if (version === mutationVersion.current) setJobs((current) => (same(current, nextJobs) ? current : nextJobs));
    },
    // A failure streak is reported once so repeated polls do not overwrite the user's own action errors.
    onError: (cause) => {
      if (failing.current) return;
      failing.current = true;
      onError(String(cause));
    },
    errorPolicy: "retry",
  });
  return { status, jobs, setJobs, mutationVersion };
}
