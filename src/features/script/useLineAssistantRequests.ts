import { api } from "../../api";
import type { StudioProject } from "../../types";
import type { ProjectEditSession } from "../studio/projectEditSession";
import type { ScriptAssistantJob } from "./scriptAssistantTypes";

type Model = {
  projectSession: Pick<ProjectEditSession, "save" | "runServer" | "requestProject">;
  validate: () => boolean;
  payload: () => Parameters<typeof api.startScriptAssistantJob>[0];
  instruction: string;
  setInstruction: (value: string) => void;
  job: ScriptAssistantJob | null;
  setJob: (job: ScriptAssistantJob | null) => void;
  acceptedRows: Set<string>;
  acceptedGroups: Set<string>;
  onBusy: (value: string | null) => void;
  onNotice: (message: string) => void;
  onGenerated: (project: StudioProject) => void;
};
export function useLineAssistantRequests(model: Model) {
  const { projectSession, validate, payload, instruction, setInstruction, job, setJob, acceptedRows, acceptedGroups, onBusy, onNotice, onGenerated } = model;
  async function startGeneration() {
    if (!validate()) return;
    onBusy("script-assistant-generate");
    setJob(null);
    try {
      if (!(await projectSession.save())) return onBusy(null);
      const next = await projectSession.runServer(() => api.startScriptAssistantJob(payload()));
      if (next) setJob(next);
    } catch (error) {
      onBusy(null);
      onNotice(`台本を提案できませんでした: ${(error as Error).message}`);
    }
  }
  async function refine(sourceInstruction = instruction) {
    if (!validate()) return;
    const randomIdea = !sourceInstruction.trim();
    onBusy("script-assistant-refine");
    try {
      if (!(await projectSession.save())) return;
      const result = await projectSession.runServer(() => api.suggestScriptAssistant({ ...payload(), instruction: sourceInstruction }));
      if (!result) return;
      setInstruction(result.instruction);
      onNotice(randomIdea ? "前後の文脈から台本内容案を入力しました。" : "アイディアを台本の文脈に合わせて広げました。");
    } catch (error) {
      onNotice(`要望を校正できませんでした: ${(error as Error).message}`);
    } finally {
      onBusy(null);
    }
  }
  async function applyProposal() {
    if (!job?.proposalId || !job.sourceSignature) return;
    onBusy("script-assistant-apply");
    try {
      const next = await projectSession.requestProject(() =>
        api.applyScriptAssistantProposal(job.proposalId!, {
          source_signature: job.sourceSignature!,
          accepted_row_ids: [...acceptedRows],
          accepted_group_ids: [...acceptedGroups],
        }),
      );
      if (next) onGenerated(next);
    } catch (error) {
      onNotice(`提案を適用できませんでした: ${(error as Error).message}`);
    } finally {
      onBusy(null);
    }
  }
  return { startGeneration, refine, applyProposal };
}
