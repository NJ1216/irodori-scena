import { useEffect, useRef } from "react";
import { CastTerminology, OverlayDismissal } from "../shared/overlays";
import { PrimaryScrollbars } from "../shared/PrimaryScrollbars";
import { FileDropOverlay } from "./FileDropOverlay";
import { LineJumpOverlay } from "./LineJumpOverlay";
import { MainWindowFooter } from "./MainWindowFooter";
import { ProjectLoadingOverlay } from "./ProjectLoadingOverlay";
import { StudioActiveView } from "./StudioActiveView";
import { StudioDialogs } from "./StudioDialogs";
import { RhubarbStartupUpdate } from "./RhubarbStartupUpdate";
import { StudioHeader } from "./StudioHeader";
import { loadCharactersView } from "./secondaryTabLoaders";
import { useStudioFileDrop } from "./useStudioFileDrop";
import { useStudioHeaderHeight } from "./useStudioHeaderHeight";
import { useOsFileOpen } from "./useOsFileOpen";
import type { StudioController } from "./useStudioController";

export function StudioShell({ model }: { model: StudioController }) {
  const shellRef = useRef<HTMLElement | null>(null);
  const headerRef = useRef<HTMLDivElement | null>(null);
  const draggedFiles = useStudioFileDrop(model);
  useOsFileOpen(model);
  useStudioHeaderHeight(shellRef, headerRef, Boolean(model.project));
  useEffect(() => {
    const preload = () => void loadCharactersView();
    const idleId = window.requestIdleCallback?.(preload, { timeout: 1500 });
    if (idleId !== undefined) return () => window.cancelIdleCallback(idleId);
    const timeoutId = window.setTimeout(preload, 400);
    return () => window.clearTimeout(timeoutId);
  }, []);
  if (!model.project)
    return (
      <main className="boot">
        <div className="boot-card">🌸 {model.notice}</div>
      </main>
    );
  const projectLoading = model.busy === "open-workspace";
  return (
    <main ref={shellRef} className={`app-shell app-shell--${model.tab}`} inert={projectLoading} aria-hidden={projectLoading || undefined}>
      <OverlayDismissal />
      <CastTerminology />
      <PrimaryScrollbars tab={model.tab} />
      <LineJumpOverlay />
      <StudioHeader model={model} headerRef={headerRef} />
      <StudioActiveView model={model} />
      <MainWindowFooter onInsertEmoji={model.insertExpressionEmoji} />
      <StudioDialogs model={model} />
      <RhubarbStartupUpdate />
      <FileDropOverlay drop={draggedFiles} />
      <ProjectLoadingOverlay visible={projectLoading} />
    </main>
  );
}
