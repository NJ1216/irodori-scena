import { describe, expect, it } from "vitest";
import { memorySnapshotForTopology } from "./acceleratorTopology";

describe("startup accelerator topology", () => {
  it("creates split RAM and VRAM before dynamic dedicated-memory samples arrive", () => {
    const snapshot = memorySnapshotForTopology({ kind: "dedicated", adapterId: "gpu-1", dedicatedBytes: 12_000, dedicatedUsedBytes: 3_000, gpuUtilizationPercent: 24 });
    expect(snapshot).toMatchObject({ kind: "split", ram: { totalBytes: null }, vram: { totalBytes: 12_000, availableBytes: 9_000 }, gpuUtilizationPercent: 24 });
  });

  it.each(["unified", "system-only"] as const)("keeps %s on the single-memory path", (kind) => {
    expect(memorySnapshotForTopology({ kind, adapterId: null, dedicatedBytes: null, dedicatedUsedBytes: null, gpuUtilizationPercent: null }).kind).toBe("unified");
  });
});
