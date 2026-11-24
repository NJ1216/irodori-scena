import type { Dispatch, SetStateAction } from "react";

export const PROJECT_SWITCH_CLICK_GUARD_MS = 750;

export function releaseProjectSwitchBusy(setBusy: Dispatch<SetStateAction<string | null>>, busyState: string) {
  window.setTimeout(() => {
    setBusy((current) => (current === busyState ? null : current));
  }, PROJECT_SWITCH_CLICK_GUARD_MS);
}
