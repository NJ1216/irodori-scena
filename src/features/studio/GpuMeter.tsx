import { ResourceMeterIcon } from "./ResourceMeterIcon";

export function GpuMeter({ percent }: { percent: number | null }) {
  const rounded = percent == null ? null : Math.round(percent);
  const value = rounded == null ? "—%" : `${rounded}%`;
  const tooltip = "GPU使用率（1秒ごとに取得、直近3秒のピーク）";
  return (
    <div className="gpu-meter" data-tooltip={tooltip} tabIndex={0} aria-label={`GPU使用率: ${value}。1秒ごとに取得、直近3秒のピーク`}>
      <span className="gpu-meter-label">
        <ResourceMeterIcon name="gpu" label="GPU使用率" />
      </span>
      <span className="gpu-meter-bar" role="meter" aria-label={tooltip} aria-valuemin={0} aria-valuemax={100} aria-valuenow={rounded ?? undefined}>
        <i style={{ width: `${rounded ?? 0}%` }} />
      </span>
      <span className="gpu-meter-value">{value}</span>
    </div>
  );
}
