import { useEffect } from "react";

import { api } from "../../api";
import { StudioShell } from "./StudioShell";
import { useStudioController } from "./useStudioController";

export function StudioApp() {
  useEffect(() => {
    let lastSent = 0;
    const notify = () => {
      const now = performance.now();
      if (now - lastSent < 80) return;
      lastSent = now;
      void api.notifyInferenceInteraction().catch(() => undefined);
    };
    window.addEventListener("pointerdown", notify, { capture: true, passive: true });
    window.addEventListener("keydown", notify, { capture: true });
    window.addEventListener("wheel", notify, { capture: true, passive: true });
    return () => {
      window.removeEventListener("pointerdown", notify, true);
      window.removeEventListener("keydown", notify, true);
      window.removeEventListener("wheel", notify, true);
    };
  }, []);
  return <StudioShell model={useStudioController()} />;
}
