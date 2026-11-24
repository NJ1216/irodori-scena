import { lazy } from "react";
import { CastImportDialog, CastImportSkippedDialog } from "../characters/CastImportDialog";
import { AiDirectionDialog } from "../direction/AiDirectionDialog";
import { ScriptImportDialog } from "../script/ScriptImportDialog";
import { AutoGenerationConflictDialog } from "./AutoGenerationConflictDialog";
import { FirstRunSetupDialog } from "./FirstRunSetupDialog";
import { GlobalCastUpdatesDialog } from "./GlobalCastUpdatesDialog";
import { ProjectMaintenanceDialog } from "./ProjectMaintenanceDialog";
import { rewriteFocusAfterApply } from "./rewriteFocusAfterApply";
import type { StudioController } from "./useStudioController";

const LineAssistantDialog = lazy(() => import("../script/LineAssistantDialog").then((module) => ({ default: module.LineAssistantDialog })));
const ExportDialog = lazy(() => import("../export/ExportDialog").then((module) => ({ default: module.ExportDialog })));
const DraftCompletionDialog = lazy(() => import("../draft/DraftCompletionDialog").then((module) => ({ default: module.DraftCompletionDialog })));
const CastExportDialog = lazy(() => import("../characters/CastExportDialog").then((module) => ({ default: module.CastExportDialog })));

export function DraftAndSuggestionDialogs({ model }: { model: StudioController }) {
  const { project } = model;
  if (!project) return null;
  const completeLineAssistant = (next: NonNullable<StudioController["project"]>) => {
    const { lineAssistantTarget, focusedLineId } = model;
    if (!lineAssistantTarget) return;
    if (lineAssistantTarget.kind === "rewrite") {
      const nextFocusId = rewriteFocusAfterApply(project, next, lineAssistantTarget.lineIds, focusedLineId);
      model.setFocusedLineId(nextFocusId);
      model.setSelectedLineIds(nextFocusId ? [nextFocusId] : []);
      model.setSelectionAnchorLineId(nextFocusId);
      if (nextFocusId) requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-line-id="${CSS.escape(nextFocusId)}"]`)?.focus());
    }
    model.setLineAssistantTarget(null);
    model.setNotice("AIの台本提案を適用しました。内容を確認してから音声を生成してください。");
  };
  return (
    <>
      {model.draftCompletionSummary && <DraftCompletionDialog job={model.draftCompletionSummary} onClose={() => model.setDraftCompletionSummary(null)} />}
      <ScriptImportDialog model={model} />
      {model.autoGenerationConflictAction && <AutoGenerationConflictDialog action={model.autoGenerationConflictAction} onClose={() => model.setAutoGenerationConflictAction(null)} onContinue={() => void model.continueProjectMenuAction()} />}
      {model.lineAssistantTarget && (
        <LineAssistantDialog
          projectSession={model.editSession}
          project={project}
          connection={model.connection}
          connectionReady={model.connectionReady}
          target={model.lineAssistantTarget}
          busy={model.busy}
          onBusy={model.setBusy}
          onClose={() => model.setLineAssistantTarget(null)}
          onGenerated={completeLineAssistant}
          onNotice={model.setNotice}
        />
      )}
    </>
  );
}

export function ProjectMaintenanceDialogs({ model }: { model: StudioController }) {
  return (
    <>
      {model.projectMaintenanceAction && (
        <ProjectMaintenanceDialog
          action={model.projectMaintenanceAction}
          onClose={() => model.setProjectMaintenanceAction(null)}
          onConfirm={() => {
            const action = model.projectMaintenanceAction;
            model.setProjectMaintenanceAction(null);
            void (action === "new" ? model.createNewProject() : model.clearAllTakes(true));
          }}
        />
      )}
      {model.globalCastUpdates && <GlobalCastUpdatesDialog characters={model.globalCastUpdates} busy={model.busy === "apply-global-cast-updates"} onKeepProject={() => model.setGlobalCastUpdates(null)} onApply={() => void model.applyGlobalCastUpdates()} />}
      {model.exportDialogOpen && <ExportDialog project={model.project!} job={model.exportJob} onClose={() => model.setExportDialogOpen(false)} onStart={model.startExportBundle} onCancel={model.cancelExport} />}
    </>
  );
}

export function CastTransferDialogs({ model }: { model: StudioController }) {
  return (
    <>
      {model.castExportDialogOpen && <CastExportDialog characters={model.project!.characters} onClose={() => model.setCastExportDialogOpen(false)} />}
      {model.castImportPreparation && (
        <CastImportDialog
          preparation={model.castImportPreparation}
          onClose={() => model.setCastImportPreparation(null)}
          onApplied={(next, message, skipped) => {
            model.applyCastImportProject(next);
            model.setNotice(message);
            model.setCastImportPreparation(null);
            model.setSkippedImports(skipped);
          }}
        />
      )}
      {model.skippedImports.length > 0 && <CastImportSkippedDialog skipped={model.skippedImports} onClose={() => model.setSkippedImports([])} />}
    </>
  );
}

export function SetupAndDirectionDialogs({ model }: { model: StudioController }) {
  return (
    <>
      <FirstRunSetupDialog
        onOpenLlmSettings={() => {
          model.setSettingsFocusRequested(true);
          model.setTab("settings");
        }}
      />
      {model.aiDirectionOpen && <AiDirectionDialog projectSession={model.editSession} project={model.project!} connection={model.connection} onClose={() => model.setAiDirectionOpen(false)} onComplete={model.forceAiDirectionAutoRender} onNotice={model.setNotice} />}
    </>
  );
}
