import type { ReactNode } from "react";
import type { DraftJob } from "../../types";
import { formatDuration, formatElapsedClock } from "../shared/studio-utils";
import { DialogFooter, DialogHeader } from "../shared/overlays";

type GenerationProgressJob = {
  status?: string;
  phase: string;
  message?: string;
  notationCompletedSteps?: number;
  notationTotalSteps?: number;
  performanceCompletedLines?: number;
  performanceTotalLines?: number;
  draftFinishingStepRequired?: boolean;
  performanceFallbackStepRequired?: boolean;
  cancelRequested?: boolean;
  receivedCharacters?: number;
  estimatedGeneratedCharacters?: number | null;
};

type GenerationPhase = readonly [string, string];

const draftPhases: GenerationPhase[] = [
  ["context", "キャラクターの設定をまとめています"],
  ["planning", "台本のあらすじを作成中"],
  ["dialogue", "台詞を執筆中"],
];

function visibleDraftPhases(job: GenerationProgressJob): GenerationPhase[] {
  return [...draftPhases, ...(job.draftFinishingStepRequired ? ([["finishing", "台本を仕上げています"]] as GenerationPhase[]) : []), ...(job.performanceFallbackStepRequired ? ([["performance", "演技と間を整えています"]] as GenerationPhase[]) : [])];
}

function currentPhaseIndex(job: GenerationProgressJob, phases: GenerationPhase[]): number {
  const indexes = Object.fromEntries(phases.map(([phase], index) => [phase, index]));
  if (job.phase === "completed") return phases.length;
  if (job.phase === "failed" || job.phase === "cancelled") {
    return Math.max(0, phases.length - 1);
  }
  const dialogueIndex = indexes.dialogue ?? 0;
  if (job.phase === "repairing" || job.phase === "notation") return indexes.finishing ?? dialogueIndex;
  if (job.phase === "performance") return indexes.performance ?? indexes.finishing ?? dialogueIndex;
  const initialIndexes: Record<string, number> = { starting: 0, context: 0, planning: 1, dialogue: 2 };
  return indexes[job.phase] ?? initialIndexes[job.phase] ?? 0;
}

function GenerationProgressBar({ active, indeterminate, label, progress }: { active: boolean; indeterminate: boolean; label: string; progress: number }) {
  return (
    <span className={`progress-bar${indeterminate ? "" : " determinate"}${active ? " is-active" : ""}`} role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={indeterminate ? undefined : Math.floor(progress)}>
      <i style={{ width: `${progress}%` }} />
    </span>
  );
}

function inFlightCharacters(job: GenerationProgressJob, generatedCharacters: number): number | null {
  if (job.phase !== "dialogue" || !job.receivedCharacters || job.estimatedGeneratedCharacters == null) return null;
  return Math.max(generatedCharacters, job.estimatedGeneratedCharacters);
}

function DraftProgressMetrics({ job, elapsed, generatedCharacters, targetCharacters, overallProgress, progressLabel, indeterminate }: { job: GenerationProgressJob; elapsed: number; generatedCharacters: number; targetCharacters: number; overallProgress: number; progressLabel: string; indeterminate: boolean }) {
  let workLabel = job.phase === "dialogue" ? "目標文字数" : "台本の長さ";
  const estimated = inFlightCharacters(job, generatedCharacters);
  let workValue = `${Math.round(estimated ?? generatedCharacters).toLocaleString()} / ${targetCharacters.toLocaleString()}文字`;
  if (job.phase === "notation") {
    workLabel = "仕上げ";
    workValue = `${job.notationCompletedSteps ?? 0} / ${job.notationTotalSteps ?? 3}工程`;
  } else if (job.phase === "performance") {
    workLabel = "演技設定";
    workValue = `${job.performanceCompletedLines ?? 0} / ${job.performanceTotalLines ?? 0}行`;
  }
  return (
    <div className="draft-generation-status" role="status">
      <div className="draft-generation-status-top">
        <p className="draft-generation-activity">
          {job.message?.replace(/[.…]+$/, "")}
          <span className="draft-generation-dots" aria-hidden="true">
            ...
          </span>
        </p>
        <p className="draft-generation-overall">
          <span>全体進捗</span>
          <strong>{Math.floor(overallProgress)}%</strong>
        </p>
      </div>
      <GenerationProgressBar active={job.status === "planning" || job.status === "generating"} indeterminate={indeterminate} label={progressLabel} progress={overallProgress} />
      <div className="draft-generation-status-bottom">
        <span>
          <b>{workLabel}</b> {workValue}
        </span>
        <span>
          <b>経過時間</b> {formatElapsedClock(elapsed)}
        </span>
      </div>
    </div>
  );
}

export function DraftGenerationDialog({
  job,
  elapsed,
  generatedCharacters,
  targetCharacters,
  overallProgress,
  onCancel,
  eyebrow = "AI SCRIPT DRAFT",
  title = "台本を生成しています",
  phases,
  progressLabel = "AI台本生成の全体進捗",
  progressMetrics,
  cancelLabel = "生成をキャンセル",
  actionLabel,
  onAction,
  indeterminate = false,
}: {
  job: GenerationProgressJob;
  elapsed: number;
  generatedCharacters: number;
  targetCharacters: number;
  overallProgress: number;
  onCancel: () => Promise<void>;
  eyebrow?: string;
  title?: string;
  phases?: GenerationPhase[];
  progressLabel?: string;
  progressMetrics?: ReactNode;
  cancelLabel?: string;
  actionLabel?: string;
  onAction?: () => void;
  indeterminate?: boolean;
}) {
  const displayedPhases = phases ?? visibleDraftPhases(job);
  const phaseIndex = currentPhaseIndex(job, displayedPhases);
  return (
    <div className="modal-backdrop draft-generation-backdrop">
      <section className="modal draft-generation-modal" role="dialog" aria-modal="true" aria-labelledby="draft-generation-title">
        <DialogHeader eyebrow={eyebrow} title={title} titleId="draft-generation-title" />
        <ol className="draft-generation-steps" aria-label="生成工程">
          {displayedPhases.map(([phase, label], index) => {
            const state = index < phaseIndex ? "is-complete" : index === phaseIndex ? "is-current" : "is-pending";
            return (
              <li className={state} key={phase}>
                <span aria-hidden="true">
                  <span className="circle-number-glyph">{state === "is-complete" ? "✓" : index + 1}</span>
                </span>
                {label}
              </li>
            );
          })}
        </ol>
        {progressMetrics ? (
          <>
            <GenerationProgressBar active={job.status === "planning" || job.status === "generating"} indeterminate={indeterminate} label={progressLabel} progress={overallProgress} />
            <div className="draft-generation-metrics" role="status">
              {progressMetrics}
            </div>
          </>
        ) : (
          <DraftProgressMetrics job={job} elapsed={elapsed} generatedCharacters={generatedCharacters} targetCharacters={targetCharacters} overallProgress={overallProgress} progressLabel={progressLabel} indeterminate={indeterminate} />
        )}
        <DialogFooter className="draft-generation-actions">
          <button type="button" className="draft-cancel-button" disabled={Boolean(job.cancelRequested && !actionLabel)} onClick={() => void (onAction ?? onCancel)()}>
            {actionLabel ?? (job.cancelRequested ? "キャンセル処理中…" : cancelLabel)}
          </button>
        </DialogFooter>
      </section>
    </div>
  );
}

export function DraftResult({ job }: { job: DraftJob }) {
  return (
    <section className="draft-preview">
      <div>
        <p className="eyebrow">{job.status === "completed" ? "ADDED TO SCRIPT" : job.completedChunks > 0 ? "PARTIALLY ADDED" : "GENERATION STOPPED"}</p>
        <h2>{job.title || "AI台本"}</h2>
        <span>
          {job.appendedLines} 行を追加・同時発話 {job.appendedCueCount ?? 0}組・推定尺 {formatDuration(job.estimatedSeconds)}
        </span>
      </div>
      <p className="subtle">{job.status === "completed" ? "生成済みの台本は自動的に追加されました。台本タブで確認・編集してから音声を生成できます。" : `${job.message}${job.error ? ` ${job.error}` : ""}`}</p>
    </section>
  );
}
