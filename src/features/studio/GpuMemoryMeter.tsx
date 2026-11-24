import { ResourceMeterIcon } from "./ResourceMeterIcon";

const gb = (value: number) => `${(value / 1_000_000_000).toFixed(1)}GB`;

type Props = { used?: number | null; total?: number | null; other?: number | null; llm?: number | null; tts?: number | null };

function memorySegments(total: number, values: Array<{ label: string; value: number; index: number }>) {
  let left = 0;
  return values.flatMap(({ label, value, index }) => {
    const width = (Math.max(0, value) / total) * 100;
    const segment = width > 0 ? [{ label, value, index, left, width }] : [];
    left += width;
    return segment;
  });
}

export function GpuMemoryMeter({ used, total, other, llm, tts }: Props) {
  if (total == null || total <= 0) return null;
  const boundedUsed = used == null ? null : Math.max(0, Math.min(used, total));
  const available = boundedUsed == null ? null : total - boundedUsed;
  const tooltip = boundedUsed == null ? `NVIDIA GPUメモリ: 使用量を取得中 / ${gb(total)}` : `NVIDIA GPUメモリ: ${gb(boundedUsed)} / ${gb(total)} 使用中`;
  const detailed = boundedUsed != null && other != null && llm != null && tts != null;
  const values = detailed
    ? [
        { label: "その他", value: other, index: 0 },
        { label: "LLM", value: llm, index: 2 },
        { label: "Irodori-TTS", value: tts, index: 3 },
        { label: "空き", value: Math.max(0, total - boundedUsed!), index: 4 },
      ]
    : boundedUsed == null
      ? []
      : [{ label: "使用中", value: boundedUsed, index: 0 }];
  const segments = memorySegments(total, values);
  return (
    <div className="gpu-meter gpu-memory-meter" aria-label={tooltip}>
      <span className="gpu-meter-label">
        <ResourceMeterIcon name="gpuMemory" label="GPUメモリ" />
      </span>
      <span className="gpu-meter-bar" role="meter" aria-label="NVIDIA GPUメモリ使用量" aria-valuemin={0} aria-valuemax={total} aria-valuenow={boundedUsed ?? undefined}>
        <span className="gpu-memory-track" aria-hidden="true">
          {segments.map((segment) => (
            <i key={segment.label} className={detailed ? `memory-part-${segment.index}` : undefined} style={{ left: `${segment.left}%`, width: `${segment.width}%` }} />
          ))}
        </span>
        {segments.map((segment) => (
          <span key={segment.label} className="memory-part-hit gpu-memory-part-hit" style={{ left: `${segment.left}%`, width: `${segment.width}%` }} data-tooltip={`${segment.label} ${gb(segment.value)}`} tabIndex={0} aria-label={`GPUメモリ ${segment.label} ${gb(segment.value)}`} />
        ))}
      </span>
      <span className="gpu-meter-value">{available == null ? "—" : gb(available)} 空き</span>
    </div>
  );
}
