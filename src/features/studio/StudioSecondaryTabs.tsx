import { lazy, Suspense } from "react";
import type { StudioController } from "./useStudioController";
import { loadDraftView, loadSettingsView } from "./secondaryTabLoaders";
import { LazyLoadBoundary } from "../shared/LazyLoadBoundary";
const LoraManagementView = lazy(() => import("../lora/LoraTrainingView").then((module) => ({ default: module.LoraManagementView })));
const DraftView = lazy(loadDraftView);
const SettingsView = lazy(loadSettingsView);

export function StudioSecondaryTabs({ model }: { model: StudioController }) {
  const { tab, project, workspace, connection, draftJob, draftComposer, setDraftComposer, busy, startDraftJob, cancelDraftJob, setNotice, setBusy, setConnection, editSession } = model;
  if (!project) return null;
  const operation = editSession.capture();
  if (tab === "lora")
    return (
      <LazyLoadBoundary>
        <Suspense fallback={<div className="boot-card">LoRA管理を読み込んでいます…</div>}>
          <LoraManagementView />
        </Suspense>
      </LazyLoadBoundary>
    );
  if (tab === "draft")
    return (
      <LazyLoadBoundary>
        <Suspense fallback={<div className="boot-card">AI台本を読み込んでいます…</div>}>
          <DraftView project={project} connection={connection} job={draftJob} composer={draftComposer} onComposerChange={setDraftComposer} busy={busy} onStartJob={startDraftJob} onCancelJob={cancelDraftJob} onNotice={setNotice} onBusy={setBusy} />
        </Suspense>
      </LazyLoadBoundary>
    );
  if (tab === "settings")
    return (
      <LazyLoadBoundary>
        <Suspense fallback={<div className="boot-card">設定を読み込んでいます…</div>}>
          <SettingsView
            focusLlmHeading={model.settingsFocusRequested}
            onHeadingFocused={() => model.setSettingsFocusRequested(false)}
            connection={connection}
            isScratch={workspace?.isScratch ?? true}
            onChange={setConnection}
            onTtsSelectionChange={(ttsSelection) => editSession.applyServerUpdate(operation, (current) => ({ ...current, ttsSelection }))}
          />
        </Suspense>
      </LazyLoadBoundary>
    );
  return null;
}
