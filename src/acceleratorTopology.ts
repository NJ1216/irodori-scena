import type { MemorySnapshot } from "./types";

export type AcceleratorTopology = {
  kind: "unified" | "dedicated" | "system-only";
  adapterId: string | null;
  dedicatedBytes: number | null;
  dedicatedUsedBytes: number | null;
  gpuUtilizationPercent: number | null;
};

let startupTopology: AcceleratorTopology = { kind: "system-only", adapterId: null, dedicatedBytes: null, dedicatedUsedBytes: null, gpuUtilizationPercent: null };

export async function detectStartupTopology(): Promise<void> {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    startupTopology = await invoke<AcceleratorTopology>("accelerator_topology");
  } catch {
    // Browser-only development has no authoritative accelerator descriptor.
  }
}

const empty = (totalBytes: number | null = null) => ({
  totalBytes,
  availableBytes: null,
  otherUsedBytes: null,
  scenaAppBytes: null,
  llmBytes: null,
  ttsBytes: null,
});

export function memorySnapshotForTopology(topology: AcceleratorTopology): MemorySnapshot {
  if (topology.kind === "dedicated" && topology.dedicatedBytes != null) {
    const used = topology.dedicatedUsedBytes == null ? null : Math.max(0, Math.min(topology.dedicatedUsedBytes, topology.dedicatedBytes));
    return {
      kind: "split",
      ram: empty(),
      vram: { ...empty(topology.dedicatedBytes), availableBytes: used == null ? null : topology.dedicatedBytes - used },
      acceleratorOwner: null,
      gpuUtilizationPercent: topology.gpuUtilizationPercent,
      sampledAt: 0,
    };
  }
  return {
    kind: "unified",
    ...empty(),
    metalOwner: null,
    gpuUtilizationPercent: topology.gpuUtilizationPercent,
    sampledAt: 0,
  };
}

export function initialMemorySnapshot(): MemorySnapshot {
  return memorySnapshotForTopology(startupTopology);
}
