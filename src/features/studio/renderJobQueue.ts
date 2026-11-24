import type { DialogueLine, StudioProject } from "../../types";
import { isMeanFlowSelection } from "../shared/ttsSampling";

export type RenderJobCause = "playback-required" | "manual-new-take" | "manual-replace" | "manual-seed" | "last-take-deleted" | "line-edited" | "ai-direction" | "dictionary" | "missing-take";

export type RenderJob = {
  jobId: string;
  lineId: string;
  mode: "append" | "replace";
  seed?: number;
  targetTakeId?: string;
  historyBaseRevision?: number;
  historyGroupId?: string;
  missingAudioTakeId?: string;
  cause: RenderJobCause;
  projectId: string;
  projectGeneration: number;
  renderSignature: string;
  enqueueSequence: number;
  interruptionCount: number;
};

const manualCauses = new Set<RenderJobCause>(["manual-new-take", "manual-replace", "manual-seed"]);
const missingCauses = new Set<RenderJobCause>(["playback-required", "last-take-deleted", "missing-take"]);
const missingCauseUrgency: Partial<Record<RenderJobCause, number>> = {
  "playback-required": 3,
  "last-take-deleted": 2,
  "missing-take": 1,
};
let renderSequence = 0;

function priority(job: RenderJob) {
  if (manualCauses.has(job.cause)) return 1;
  if (job.cause === "line-edited") return 2;
  if (job.cause === "playback-required") return 3;
  return 4;
}

export function nextRenderSequence() {
  renderSequence += 1;
  return renderSequence;
}

function hash(value: string) {
  let result = 2166136261;
  for (let index = 0; index < value.length; index += 1) result = Math.imul(result ^ value.charCodeAt(index), 16777619);
  return (result >>> 0).toString(16).padStart(8, "0");
}

export function lineRenderSignature(project: StudioProject, line: DialogueLine) {
  const character = project.characters?.find((item) => item.id === line.characterId);
  const meanflow = isMeanFlowSelection(project.ttsSelection);
  const sampling = meanflow
    ? { steps: 4 }
    : {
        textCfg: line.textCfg ?? project.settings.textCfg,
        voiceCfg: line.voiceCfg ?? project.settings.voiceCfg,
        captionCfg: line.captionCfg ?? project.settings.captionCfg,
        quality: project.settings.quality,
        steps: project.settings.steps,
      };
  return hash(
    JSON.stringify({
      text: line.text,
      pronunciations: line.pronunciations ?? [],
      stageDirection: line.stageDirection,
      characterId: line.characterId,
      referenceVersion: character?.referenceVersion ?? 0,
      lora: character?.lora,
      loraMix: character?.loraMix,
      speechRate: line.speechRate ?? project.settings.speechRate,
      sampling,
      targetDurationSeconds: line.targetDurationSeconds,
      ttsSelection: project.ttsSelection,
    }),
  );
}

export function createRenderJob(project: StudioProject, line: DialogueLine, sequence: number, options: Pick<RenderJob, "mode" | "cause"> & Partial<Pick<RenderJob, "seed" | "targetTakeId" | "missingAudioTakeId" | "historyBaseRevision" | "historyGroupId">>, projectGeneration = 0): RenderJob {
  return {
    jobId: crypto.randomUUID(),
    lineId: line.id,
    ...options,
    projectId: project.id,
    projectGeneration,
    renderSignature: lineRenderSignature(project, line),
    enqueueSequence: sequence,
    interruptionCount: 0,
  };
}

function removeObsoleteEditJobs(queue: RenderJob[], job: RenderJob) {
  if (job.cause !== "line-edited") return;
  for (let index = queue.length - 1; index >= 0; index -= 1) {
    if (queue[index].lineId === job.lineId && !manualCauses.has(queue[index].cause)) queue.splice(index, 1);
  }
}

export function enqueueRenderJobs(queue: RenderJob[], jobs: RenderJob[]) {
  const next = [...queue];
  for (const job of jobs) {
    let queuedJob = job;
    if (!manualCauses.has(job.cause)) {
      removeObsoleteEditJobs(next, job);
      const matchingMissing = missingCauses.has(job.cause) ? next.filter((queued) => queued.lineId === job.lineId && missingCauses.has(queued.cause)) : [];
      const strongerMissing = matchingMissing.find((queued) => (missingCauseUrgency[queued.cause] ?? 0) > (missingCauseUrgency[job.cause] ?? 0));
      if (strongerMissing?.renderSignature === job.renderSignature) continue;
      if (strongerMissing) queuedJob = { ...job, cause: strongerMissing.cause, interruptionCount: Math.max(job.interruptionCount, strongerMissing.interruptionCount) };
      for (let index = next.length - 1; index >= 0; index -= 1) {
        const queued = next[index];
        const sameIntent = queued.cause === job.cause || (missingCauses.has(queued.cause) && missingCauses.has(job.cause));
        if (queued.lineId === job.lineId && sameIntent) next.splice(index, 1);
      }
    }
    next.push(queuedJob);
  }
  return next.sort((left, right) => priority(left) - priority(right) || left.enqueueSequence - right.enqueueSequence);
}

export function dequeueRenderJob(queue: RenderJob[], project: StudioProject, protectedLineIds: ReadonlySet<string>) {
  const lineOrder = new Map(project.scenes.flatMap((scene) => scene.lines).map((line, index) => [line.id, index]));
  let selectedIndex = -1;
  for (let index = 0; index < queue.length; index += 1) {
    const candidate = queue[index];
    if (candidate.cause !== "playback-required" && protectedLineIds.has(candidate.lineId)) continue;
    if (selectedIndex < 0) {
      selectedIndex = index;
      continue;
    }
    const selected = queue[selectedIndex];
    const tierDifference = priority(candidate) - priority(selected);
    const orderDifference = priority(candidate) >= 3 ? (lineOrder.get(candidate.lineId) ?? Number.MAX_SAFE_INTEGER) - (lineOrder.get(selected.lineId) ?? Number.MAX_SAFE_INTEGER) : candidate.enqueueSequence - selected.enqueueSequence;
    if (tierDifference < 0 || (tierDifference === 0 && (orderDifference < 0 || (orderDifference === 0 && candidate.enqueueSequence < selected.enqueueSequence)))) selectedIndex = index;
  }
  return selectedIndex < 0 ? undefined : queue.splice(selectedIndex, 1)[0];
}

export function isCurrentRenderJob(project: StudioProject, line: DialogueLine, job: RenderJob, projectGeneration = job.projectGeneration) {
  if (job.projectId !== project.id || job.projectGeneration !== projectGeneration || job.renderSignature !== lineRenderSignature(project, line)) return false;
  if (missingCauses.has(job.cause) && line.takes.some((take) => take.id === line.selectedTakeId) && job.missingAudioTakeId !== line.selectedTakeId) return false;
  if (job.mode === "replace" && (!job.targetTakeId || (line.selectedTakeId !== job.targetTakeId && !(job.cause === "line-edited" && !line.selectedTakeId)) || !line.takes.some((take) => take.id === job.targetTakeId))) return false;
  return true;
}

export function requeueInterruptedJob(queue: RenderJob[], job: RenderJob) {
  if (queue.some((queued) => queued.lineId === job.lineId && queued.cause === "line-edited" && queued.enqueueSequence > job.enqueueSequence)) return queue;
  return job.interruptionCount >= 1 ? queue : enqueueRenderJobs(queue, [{ ...job, interruptionCount: 1 }]);
}
