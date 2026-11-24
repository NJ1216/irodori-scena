import { useEffect } from "react";
import { wakeContinuousPlaybackWaiters } from "./continuousPlaybackWait";
import type { StudioEffectModel } from "./studioEffectTypes";

const OPEN_DIALOG_SELECTOR = '.modal-backdrop, [aria-modal="true"]';

export function useStudioInteractionEffects(model: StudioEffectModel) {
  const {
    project,
    autoGenerateEnabled,
    busy,
    exportJob,
    continuousPlaybackWaiters,
    autoGenerateEnabledRef,
    busyRef,
    autoScrollEnabled,
    playbackHoverFollow,
    exportHoverFollow,
    autoScrollTarget,
    continuousPlayback,
    setAutoScrollEnabled,
    setPlaybackHoverFollow,
    setExportHoverFollow,
    setStatusNotice,
    processAutoRenderQueue,
  } = model;
  useEffect(() => {
    wakeContinuousPlaybackWaiters(continuousPlaybackWaiters);
  }, [project, continuousPlaybackWaiters]);
  useEffect(() => {
    autoGenerateEnabledRef.current = autoGenerateEnabled;
    wakeContinuousPlaybackWaiters(continuousPlaybackWaiters);
  }, [autoGenerateEnabled, autoGenerateEnabledRef, continuousPlaybackWaiters]);
  useEffect(() => {
    busyRef.current = busy;
    wakeContinuousPlaybackWaiters(continuousPlaybackWaiters);
  }, [busy, busyRef, continuousPlaybackWaiters]);
  useEffect(() => {
    wakeContinuousPlaybackWaiters(continuousPlaybackWaiters);
  }, [exportJob, continuousPlaybackWaiters]);
  useEffect(() => {
    if (!autoScrollEnabled && !playbackHoverFollow && !exportHoverFollow) return;
    const disable = (event: Event) => {
      if (autoScrollTarget === "playback" && !continuousPlayback) return;
      // Scrolling inside an open dialog does not move the script, so follow stays on.
      if (event.target instanceof Element && event.target.closest(OPEN_DIALOG_SELECTOR)) return;
      setAutoScrollEnabled(false);
      setPlaybackHoverFollow(false);
      setExportHoverFollow(false);
      setStatusNotice("手動スクロールを検出したため、自動スクロールを解除しました。");
    };
    const keydown = (event: KeyboardEvent) => {
      const target = event.target;
      if (target instanceof HTMLElement && target.closest("input, textarea, [contenteditable='true']")) return;
      if (["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End"].includes(event.key)) disable(event);
    };
    window.addEventListener("wheel", disable, { passive: true });
    window.addEventListener("touchmove", disable, { passive: true });
    window.addEventListener("keydown", keydown);
    return () => {
      window.removeEventListener("wheel", disable);
      window.removeEventListener("touchmove", disable);
      window.removeEventListener("keydown", keydown);
    };
  }, [autoScrollEnabled, playbackHoverFollow, exportHoverFollow, autoScrollTarget, continuousPlayback, setAutoScrollEnabled, setPlaybackHoverFollow, setExportHoverFollow, setStatusNotice]);
  useEffect(() => {
    if (!continuousPlayback && playbackHoverFollow) setPlaybackHoverFollow(false);
  }, [continuousPlayback, playbackHoverFollow, setPlaybackHoverFollow]);
  useEffect(() => {
    if (busy !== "export" && !autoGenerateEnabled && exportHoverFollow) setExportHoverFollow(false);
  }, [busy, autoGenerateEnabled, exportHoverFollow, setExportHoverFollow]);
  useEffect(() => {
    if (autoGenerateEnabled && !busy) void processAutoRenderQueue();
  }, [autoGenerateEnabled, busy, processAutoRenderQueue]);
}
