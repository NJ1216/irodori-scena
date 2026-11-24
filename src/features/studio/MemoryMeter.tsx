import type { CSSProperties } from "react";
import type { MemoryBreakdown, MemorySnapshot } from "../../types";
import { ResourceMeterIcon } from "./ResourceMeterIcon";

const labels = ["その他", "SCENA本体", "LLM", "Irodori-TTS", "空き"];
const gb = (value: number | null | undefined) => (value == null ? "—" : `${(value / 1_000_000_000).toFixed(1)}GB`);

function values(memory: MemoryBreakdown) {
  return [memory.otherUsedBytes, memory.scenaAppBytes, memory.llmBytes, memory.ttsBytes, memory.availableBytes];
}

type Segment = { index: number; label: string; left: number; width: number; value: number };

function segments(memory: MemoryBreakdown): Segment[] {
  if (!memory.totalBytes || memory.totalBytes <= 0) return [];
  let left = 0;
  return values(memory).flatMap((value, index) => {
    const width = value == null ? 0 : Math.max(0, Math.min(100, (value / memory.totalBytes!) * 100));
    const segment = value != null && value > 0 && width > 0 ? [{ index, label: labels[index], left, width, value }] : [];
    left += width;
    return segment;
  });
}

function segmentStyle(segment: Segment): CSSProperties {
  return { left: `${segment.left}%`, width: segment.index === 1 ? `max(${segment.width}%, 3px)` : `${segment.width}%` };
}

function Bar({ name, memory }: { name: string; memory: MemoryBreakdown }) {
  const parts = segments(memory);
  return (
    <span className="unified-memory-bar">
      <span className="unified-memory-track" aria-hidden="true">
        {parts.map((segment) => (
          <i key={segment.label} className={`memory-part memory-part-${segment.index}`} style={segmentStyle(segment)} />
        ))}
      </span>
      {parts.map((segment) => {
        const tooltip = `${segment.label} ${gb(segment.value)}`;
        return <span key={segment.label} className={`memory-part-hit memory-part-hit-${segment.index}`} style={segmentStyle(segment)} data-tooltip={tooltip} tabIndex={0} aria-label={`${name} ${tooltip}`} />;
      })}
    </span>
  );
}

const emptyMemory: MemoryBreakdown = {
  totalBytes: null,
  availableBytes: null,
  otherUsedBytes: null,
  scenaAppBytes: null,
  llmBytes: null,
  ttsBytes: null,
};

export function MemoryMeter({ memory }: { memory: MemorySnapshot | null }) {
  if (!memory)
    return (
      <div className="unified-memory" data-tooltip="メモリ情報を取得できません" tabIndex={0} aria-label="ユニファイドメモリ: メモリ情報を取得できません">
        <span className="unified-memory-label">
          <ResourceMeterIcon name="memory" label="メモリ" />
        </span>
        <Bar name="メモリ" memory={emptyMemory} />
        <span className="unified-memory-value">— 空き</span>
      </div>
    );
  if (memory.kind === "split") {
    return (
      <div className="unified-memory split-memory">
        <span className="unified-memory-label">
          <ResourceMeterIcon name="memory" label="RAM" />
        </span>
        <Bar name="RAM" memory={memory.ram} />
        <span className="unified-memory-label">
          <ResourceMeterIcon name="gpuMemory" label="VRAM" />
        </span>
        <Bar name="VRAM" memory={memory.vram} />
        <span className="unified-memory-value">{gb(memory.ram.availableBytes)} 空き</span>
      </div>
    );
  }
  return (
    <div className="unified-memory">
      <span className="unified-memory-label">
        <ResourceMeterIcon name="memory" label="メモリ" />
      </span>
      <Bar name="メモリ" memory={memory} />
      <span className="unified-memory-value">{gb(memory.availableBytes)} 空き</span>
    </div>
  );
}
