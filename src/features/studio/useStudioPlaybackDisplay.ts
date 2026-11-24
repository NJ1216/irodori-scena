import { useEffect } from "react";
import type { StudioState } from "./useStudioState";

type DisplayModel = Pick<StudioState, "tab" | "continuousPlayback" | "autoScrollTarget" | "autoScrollEnabled" | "playbackHoverFollow" | "exportHoverFollow" | "playingLineId" | "generatingLineId">;

function cueHeadFor(element: HTMLElement | undefined) {
  if (!element?.classList.contains("is-cue-tail")) return element;
  let previous = element.previousElementSibling;
  while (previous?.classList.contains("is-cue-member")) {
    if (previous.classList.contains("is-cue-head")) return previous as HTMLElement;
    previous = previous.previousElementSibling;
  }
  return element;
}

export function useStudioPlaybackDisplay(model: DisplayModel) {
  const { tab, continuousPlayback, autoScrollTarget, autoScrollEnabled, playbackHoverFollow, exportHoverFollow, playingLineId, generatingLineId } = model;
  useEffect(() => {
    const playbackFollowActive = autoScrollTarget === "playback" && (autoScrollEnabled || (continuousPlayback && playbackHoverFollow));
    const exportFollowActive = (autoScrollEnabled && autoScrollTarget === "export") || exportHoverFollow;
    const autoScrollLineId = playbackFollowActive ? playingLineId : exportFollowActive ? generatingLineId : null;
    if (tab !== "script" || !autoScrollLineId) return;
    const firstPlayingLineId = autoScrollLineId.split("|")[0];
    const lineElements = Array.from(document.querySelectorAll<HTMLElement>("[data-line-id]"));
    const lineElement = cueHeadFor(lineElements.find((element) => element.dataset.lineId === firstPlayingLineId));
    lineElement?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [tab, continuousPlayback, autoScrollTarget, autoScrollEnabled, playbackHoverFollow, exportHoverFollow, playingLineId, generatingLineId]);
}
