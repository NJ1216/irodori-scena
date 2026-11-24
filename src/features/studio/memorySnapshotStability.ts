import type { MemorySnapshot } from "../../types";

const breakdownKeys = ["totalBytes", "availableBytes", "otherUsedBytes", "scenaAppBytes", "llmBytes", "ttsBytes"] as const;

function retainKnownBreakdown<T extends Record<(typeof breakdownKeys)[number], number | null>>(previous: T, next: T): T {
  return { ...next, ...Object.fromEntries(breakdownKeys.map((key) => [key, next[key] ?? previous[key]])) } as T;
}

export function stabilizeMemorySnapshot(previous: MemorySnapshot | null, next: MemorySnapshot): MemorySnapshot {
  if (!previous || previous.kind !== next.kind) return next;
  if (next.kind === "split" && previous.kind === "split") {
    return {
      ...next,
      ram: retainKnownBreakdown(previous.ram, next.ram),
      vram: retainKnownBreakdown(previous.vram, next.vram),
    };
  }
  if (next.kind === "unified" && previous.kind === "unified") return retainKnownBreakdown(previous, next);
  return next;
}

export function memoryNeedsInitialFollowup(memory: MemorySnapshot): boolean {
  return memory.gpuUtilizationPercent == null || (memory.kind === "split" && memory.vram.availableBytes == null);
}
