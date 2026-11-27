import { useEffect, useRef } from "react";
import { isTerminalJobStatus } from "./jobEventMonitor";
import type { ProjectEditSession } from "./projectEditSession";

type Options = {
  job: { id: string; status: string; cancelRequested?: boolean } | null;
  editSession: ProjectEditSession;
  request: (jobId: string) => Promise<unknown>;
  setNotice: (message: string) => void;
  pendingMessage: string;
  failurePrefix: string;
};

/** Progress monitors own snapshots and terminal reconciliation; actions only acknowledge requests. */
export function useJobCancellation({ job, editSession, request, setNotice, pendingMessage, failurePrefix }: Options) {
  const lifetime = useRef<AbortSignal | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller.signal;
    return () => controller.abort();
  }, [job?.id, job?.status, editSession]);
  return async () => {
    if (!job || job.cancelRequested || isTerminalJobStatus(job.status)) return;
    const signal = lifetime.current;
    const operation = editSession.capture();
    const current = () => signal && !signal.aborted && editSession.isCurrent(operation);
    try {
      await request(job.id);
      if (current()) setNotice(pendingMessage);
    } catch (error) {
      if (current()) setNotice(`${failurePrefix}: ${(error as Error).message}`);
    }
  };
}
