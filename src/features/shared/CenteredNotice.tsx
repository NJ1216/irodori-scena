import type { ReactNode } from "react";

/** The shared card for notices shown at the center of the window, above every dialog. */
export function CenteredNotice({ tone, label, interactive = false, children }: { tone: "danger" | "neutral"; label?: string; interactive?: boolean; children: ReactNode }) {
  return (
    <aside className={`centered-notice is-${tone}${interactive ? " is-interactive" : ""}`} role="status" aria-live="polite" aria-label={label}>
      {children}
    </aside>
  );
}
