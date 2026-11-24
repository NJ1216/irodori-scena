import { api } from "../../api";
import type { ProjectEditSession } from "./projectEditSession";
import type { DraftJob } from "../../types";
import { useJobCancellation } from "./useJobCancellation";

export function useDraftJobCancellation({ draftJob, setNotice, editSession }: { draftJob: DraftJob | null; setNotice: (value: string) => void; editSession: ProjectEditSession }) {
  return useJobCancellation({
    job: draftJob,
    editSession,
    request: api.cancelAiJob,
    setNotice,
    pendingMessage: "生成のキャンセルを受け付けました。現在の処理を停止しています…",
    failurePrefix: "台本生成をキャンセルできません",
  });
}
