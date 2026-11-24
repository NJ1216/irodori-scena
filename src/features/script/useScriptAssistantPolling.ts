import { useRef, type Dispatch, type SetStateAction } from "react";
import { api } from "../../api";
import { ApiConnectionError, ApiError } from "../../api-error";
import { useSequentialPolling } from "../shared/useSequentialPolling";
import type { ScriptAssistantJob } from "./scriptAssistantTypes";

function errorPolicy(error: unknown) {
  return error instanceof ApiConnectionError || (error instanceof ApiError && ([408, 429].includes(error.status) || (error.status >= 500 && error.status < 600))) ? "retry" : "stop";
}

export function useScriptAssistantPolling({
  job,
  setJob,
  setAcceptedRows,
  setAcceptedGroups,
  onBusy,
  onNotice,
}: {
  job: ScriptAssistantJob | null;
  setJob: Dispatch<SetStateAction<ScriptAssistantJob | null>>;
  setAcceptedRows: Dispatch<SetStateAction<Set<string>>>;
  setAcceptedGroups: Dispatch<SetStateAction<Set<string>>>;
  onBusy: (value: string | null) => void;
  onNotice: (message: string) => void;
}) {
  const recovering = useRef(false);
  const running = job?.status === "planning" || job?.status === "generating";
  useSequentialPolling({
    enabled: running && !!job,
    initialDelayMs: 300,
    intervalMs: 700,
    poll: () => api.scriptAssistantJob(job!.id),
    terminal: (next) => ["completed", "failed", "cancelled"].includes(next.status),
    onResult: (next) => {
      if (recovering.current) onNotice("通信が回復しました。");
      recovering.current = false;
      setJob(next);
      if (!["completed", "failed", "cancelled"].includes(next.status)) return;
      onBusy(null);
      if (next.status === "completed") {
        setAcceptedRows(new Set(next.groups?.flatMap((group) => (group.atomic ? [] : group.rows.map((row) => row.id)))));
        setAcceptedGroups(new Set(next.groups?.filter((group) => group.atomic).map((group) => group.id)));
      } else onNotice(next.message);
    },
    errorPolicy,
    onError: (error) => {
      if (errorPolicy(error) === "retry") {
        recovering.current = true;
        onNotice(`通信の回復を待っています: ${(error as Error).message}`);
        return;
      }
      const message = `生成状態を確認できませんでした: ${(error as Error).message}`;
      setJob((current) => (current && current.id === job?.id ? { ...current, status: "failed", message } : current));
      onBusy(null);
      onNotice(message);
    },
  });
  return running;
}
