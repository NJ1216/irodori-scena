import type { ReactNode } from "react";

type LineStatusIconName = "seed" | "audio" | "compute" | "rate" | "gap" | "textCfg" | "voiceCfg" | "captionCfg";

export function LineStatusIcon({ name, tooltip }: { name: LineStatusIconName; tooltip?: string }) {
  const paths = {
    seed: <path d="M5 5h14v14H5zM9 9h.01M15 9h.01M12 12h.01M9 15h.01M15 15h.01" />,
    audio: <path d="M12 6v6l4 2M20 12a8 8 0 1 1-16 0 8 8 0 0 1 16 0z" />,
    compute: <path d="M5 19V11m5 8V7m5 12v-5m5 5V4M3 20h18" />,
    rate: <path d="M9 3h6M12 3v3M17 7l2-2M12 8v5l3 2M20 14a8 8 0 1 1-16 0 8 8 0 0 1 16 0z" />,
    gap: <path d="M12 4v16M8 7l4-3 4 3M8 17l4 3 4-3M5 8h4m6 0h4M5 16h4m6 0h4" />,
    textCfg: <path d="M5 5.5c2.5-1 4.8-.7 7 1v13c-2.2-1.7-4.5-2-7-1zM19 5.5c-2.5-1-4.8-.7-7 1v13c2.2-1.7 4.5-2 7-1z" />,
    voiceCfg: <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM5 21c.4-4.3 3.1-7 7-7s6.6 2.7 7 7" />,
    captionCfg: <path d="M4 12h16v8H4zM4 6.5l14-4 1.2 4-14 4zM9 5.1l1.2 4m3.8-5.4 1.2 4M4 15h16" />,
  } satisfies Record<LineStatusIconName, ReactNode>;

  const icon = (
    <svg className="line-status-icon" viewBox="0 0 24 24" aria-hidden="true">
      {paths[name]}
    </svg>
  );

  if (!tooltip) return icon;

  return (
    <span className="line-status-tooltip-anchor" title={tooltip}>
      {icon}
    </span>
  );
}
