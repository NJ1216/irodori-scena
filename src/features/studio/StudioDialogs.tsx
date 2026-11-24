import { Suspense } from "react";
import { LazyLoadBoundary } from "../shared/LazyLoadBoundary";
import { CastTransferDialogs, DraftAndSuggestionDialogs, ProjectMaintenanceDialogs, SetupAndDirectionDialogs } from "./StudioDialogHosts";
import type { StudioController } from "./useStudioController";

export function StudioDialogs({ model }: { model: StudioController }) {
  if (!model.project) return null;
  return (
    <LazyLoadBoundary>
      <Suspense
        fallback={
          <div className="boot-card" data-studio-dialog-loading>
            ダイアログを読み込んでいます…
          </div>
        }
      >
        <DraftAndSuggestionDialogs model={model} />
        <ProjectMaintenanceDialogs model={model} />
        <CastTransferDialogs model={model} />
        <SetupAndDirectionDialogs model={model} />
      </Suspense>
    </LazyLoadBoundary>
  );
}
