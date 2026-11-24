import type { ReactNode } from "react";

type ResourceMeterIconName = "memory" | "gpuMemory" | "gpu";

const paths = {
  memory: (
    <>
      <rect x="3" y="7" width="18" height="10" rx="2" />
      <path d="M6 4v3m4-3v3m4-3v3m4-3v3M6 17v3m4-3v3m4-3v3m4-3v3M6.5 10h3v4h-3zm4 0h3v4h-3zm4 0h3v4h-3z" />
    </>
  ),
  gpuMemory: (
    <>
      <rect x="5" y="5" width="14" height="14" rx="2" />
      <path d="M9 9h6v6H9zM8 2v3m4-3v3m4-3v3M8 19v3m4-3v3m4-3v3M2 8h3m-3 4h3m-3 4h3m14-8h3m-3 4h3m-3 4h3" />
    </>
  ),
  gpu: (
    <>
      <path d="M4.3 18a9 9 0 1 1 15.4 0M12 12l4-4" />
      <circle cx="12" cy="12" r="1.5" />
      <path d="M7.1 14.8h.01M6.4 10h.01M9 6.5h.01M14.8 6.5h.01M17.5 11h.01" />
    </>
  ),
} satisfies Record<ResourceMeterIconName, ReactNode>;

export function ResourceMeterIcon({ name, label }: { name: ResourceMeterIconName; label: string }) {
  return (
    <span className="resource-meter-icon" role="img" aria-label={label} data-tooltip={label} tabIndex={0}>
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        {paths[name]}
      </svg>
    </span>
  );
}
