import type { DraftJob } from "../../types";

function legacyDraftProgress(job: DraftJob | null, generatedCharacters: number, targetCharacters: number) {
  const phase = job?.phase ?? "";
  if (phase === "performance") {
    return 95 + Math.min(1, (job?.completedChunks ?? 0) / Math.max(1, job?.totalChunks ?? 0)) * 4;
  }
  const fixedProgress: Record<string, number> = { context: 10, planning: 10, repairing: 90, notation: 90 };
  return phase === "dialogue" ? 20 + Math.min(1, generatedCharacters / Math.max(1, targetCharacters)) * 70 : (fixedProgress[phase] ?? 0);
}

export function displayedDraftProgress(job: DraftJob | null, generatedCharacters: number, targetCharacters: number, elapsed: number): number {
  const reported = job?.overallProgress ?? legacyDraftProgress(job, generatedCharacters, targetCharacters);
  const estimated = job?.phase === "dialogue" && (job.receivedCharacters ?? 0) > 0 ? job.estimatedGeneratedCharacters : null;
  const dialogueEstimate = estimated == null ? 0 : Math.min(89, 20 + Math.min(1, estimated / Math.max(1, targetCharacters)) * 69);
  const contextEstimate = job?.phase === "context" ? Math.min(9, elapsed / 30) : 0;
  const planningEstimate = job?.phase === "planning" ? Math.min(19, 10 + elapsed / 30) : 0;
  return Math.min(100, Math.max(0, reported, dialogueEstimate, contextEstimate, planningEstimate));
}
