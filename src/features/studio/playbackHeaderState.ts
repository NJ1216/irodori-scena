import type { Tab } from "./types";

export function disablePlaybackToggle(tab: Tab, busy: string | null, continuousPlayback: boolean) {
  return busy === "draft" || (tab !== "script" && !continuousPlayback);
}

export function playbackToggleActive(continuousPlayback: boolean) {
  return continuousPlayback;
}
