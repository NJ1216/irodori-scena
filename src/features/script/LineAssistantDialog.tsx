import { api } from "../../api";
import { useLineAssistantRequests } from "./useLineAssistantRequests";
import type { LlmConnection, StudioProject } from "../../types";
import { type LineAssistantTarget } from "../studio/types";
import { DialogHeader } from "../shared/overlays";
import { ScriptAssistantPreview } from "./ScriptAssistantPreview";
import { ScriptAssistantSettings } from "./ScriptAssistantSettings";
import { buildLineAssistantPayload, lineAssistantValidationMessage } from "./lineAssistantModel";
import { LineAssistantFooter, LineAssistantProgress } from "./LineAssistantParts";
import { useLineAssistantForm } from "./useLineAssistantForm";
import { useScriptAssistantPolling } from "./useScriptAssistantPolling";

export function LineAssistantDialog({
  project,
  projectSession,
  connection,
  connectionReady,
  target,
  busy,
  onBusy,
  onClose,
  onGenerated,
  onNotice,
}: {
  project: StudioProject;
  projectSession: Parameters<typeof useLineAssistantRequests>[0]["projectSession"];
  connection: LlmConnection;
  connectionReady: boolean;
  target: LineAssistantTarget;
  busy: string | null;
  onBusy: (value: string | null) => void;
  onClose: () => void;
  onGenerated: (project: StudioProject) => void;
  onNotice: (text: string) => void;
}) {
  const form = useLineAssistantForm(project, target);
  const { job, setJob, acceptedRows, acceptedGroups } = form;
  const insert = target.kind === "insert";
  const payload = () => buildLineAssistantPayload(project, target, form);
  const running = useScriptAssistantPolling({ job, setJob, setAcceptedRows: form.setAcceptedRows, setAcceptedGroups: form.setAcceptedGroups, onBusy, onNotice });

  const validate = () => {
    const message = lineAssistantValidationMessage(form, connection, connectionReady);
    if (message) onNotice(message);
    return !message;
  };

  const { startGeneration, refine, applyProposal } = useLineAssistantRequests({ projectSession, validate, payload, instruction: form.instruction, setInstruction: form.setInstruction, job, setJob, acceptedRows, acceptedGroups, onBusy, onNotice, onGenerated });

  async function close() {
    if (running && job) await api.cancelScriptAssistantJob(job.id).catch(() => undefined);
    onBusy(null);
    onClose();
  }

  async function cancelGeneration() {
    if (!job) return;
    try {
      setJob(await api.cancelScriptAssistantJob(job.id));
    } catch (error) {
      onNotice(`生成をキャンセルできませんでした: ${(error as Error).message}`);
    }
  }

  const preview = job?.status === "completed" && job.groups;
  if (running && job) return <LineAssistantProgress job={job} insert={insert} onCancel={cancelGeneration} />;
  return (
    <div className="modal-backdrop">
      <section className={`modal line-assistant-modal${insert ? " is-insert" : ""}`} role="dialog" aria-modal="true" aria-label="AIで台本を編集">
        <DialogHeader eyebrow="AI SCRIPT EDIT" title={insert ? "発話行を挿入" : "選択行を書き直す"} />
        {preview ? (
          <ScriptAssistantPreview groups={job.groups!} characters={project.characters} acceptedRows={acceptedRows} acceptedGroups={acceptedGroups} onRowsChange={form.setAcceptedRows} onGroupsChange={form.setAcceptedGroups} />
        ) : (
          <ScriptAssistantSettings
            target={target}
            project={project}
            onTargetLineIds={form.changeTargetLineIds}
            characters={form.settingsCharacters}
            operation={form.operation}
            targetLines={form.displayedTargetLines}
            rewriteMode={form.rewriteMode}
            onRewriteMode={form.changeRewriteMode}
            characterIds={form.characterIds}
            onCharacterIds={form.setCharacterIds}
            requiredSpeakerIds={form.requiredSpeakerIds}
            fixedCount={form.fixedCount}
            targetLineCount={form.targetLines.length}
            targetKind={form.targetKind}
            onTargetKind={form.setTargetKind}
            lineCount={form.lineCount}
            onLineCount={form.setLineCount}
            minutes={form.minutes}
            onMinutes={form.setMinutes}
            instruction={form.instruction}
            onInstruction={form.setInstruction}
            castSettings={form.castSettings}
            onCastSetting={form.changeCastSetting}
            simultaneousCues={form.simultaneousCues}
            onSimultaneousCues={form.setSimultaneousCues}
            overlappingSpeech={form.overlappingSpeech}
            onOverlappingSpeech={form.setOverlappingSpeech}
            performance={form.performance}
            onPerformance={form.setPerformance}
            sparse={form.sparse}
            busy={Boolean(busy)}
            onRefine={() => void refine()}
            onSuggestRandom={() => void refine("")}
            onGenerate={() => void startGeneration()}
          />
        )}
        <LineAssistantFooter preview={Boolean(preview)} running={running} insert={insert} busy={busy} canApply={acceptedRows.size > 0 || acceptedGroups.size > 0} onClose={() => void close()} onBackToSettings={() => setJob(null)} onApply={() => void applyProposal()} onGenerate={() => void startGeneration()} />
      </section>
    </div>
  );
}
