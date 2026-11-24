import { useEffect, useState } from "react";
import { api } from "../../api";
import type { RhubarbStatus } from "../../types";
import { RhubarbDialog } from "../settings/RhubarbSetting";

// Mounted for the studio session, so dismissal never persists across launches.
export function RhubarbStartupUpdate() {
  const [status, setStatus] = useState<RhubarbStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => {
    let active = true;
    void api
      .rhubarbStatus()
      .then((next) => {
        if (active && next.installed && next.available && next.updateAvailable) setStatus(next);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    if (!status || dismissed || open) return;
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      clearTimeout(timer);
      // Allow sibling lazy dialogs and the first-run guide to commit first.
      timer = setTimeout(() => {
        if (!document.querySelector('[role="dialog"], [aria-modal="true"], .modal-backdrop, [data-studio-dialog-loading]')) setOpen(true);
      }, 100);
    };
    const observer = new MutationObserver(schedule);
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["role", "aria-modal"] });
    schedule();
    return () => {
      clearTimeout(timer);
      observer.disconnect();
    };
  }, [status, dismissed, open]);
  const close = () => {
    setDismissed(true);
    setOpen(false);
  };
  return open && status ? <RhubarbDialog startupMode status={status} onClose={close} onReady={close} onChanged={setStatus} /> : null;
}
