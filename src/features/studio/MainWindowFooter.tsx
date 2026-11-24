import { isWindows } from "../shared/platform";
import { useEffect, useState } from "react";
import { VersionMenu } from "./VersionMenu";
import { api } from "../../api";
import type { LlmSessionUsage, MemorySnapshot } from "../../types";
import { ShortcutReference } from "../script/ShortcutReference";
import { MemoryMeter } from "./MemoryMeter";
import { memoryNeedsInitialFollowup, stabilizeMemorySnapshot } from "./memorySnapshotStability";
import { GpuMeter } from "./GpuMeter";
import { GpuMemoryMeter } from "./GpuMemoryMeter";
import { discardGpuSamples, emptyGpuUtilizationState, updateGpuUtilization } from "./gpuUtilizationAverage";
import { TokenUsageMenu } from "./TokenUsageMenu";
import { initialMemorySnapshot } from "../../acceleratorTopology";
import { MasterAudioControls } from "../shared/MasterAudioControls";
import { ExpressionPaletteMenu } from "./ExpressionPaletteMenu";

const INITIAL_REFRESH_INTERVAL_MS = 250;
const INITIAL_REFRESH_WINDOW_MS = 2_000;
const RESOURCE_REFRESH_INTERVAL_MS = 1_000;
const USAGE_REFRESH_INTERVAL_MS = 5_000;

export function MainWindowFooter({ onInsertEmoji }: { onInsertEmoji: (emoji: string) => void }) {
  const [memory, setMemory] = useState<MemorySnapshot>(initialMemorySnapshot);
  const [gpu, setGpu] = useState(() => updateGpuUtilization(emptyGpuUtilizationState, memory.gpuUtilizationPercent, memory.sampledAt));
  const [usage, setUsage] = useState<LlmSessionUsage | null>(null);
  const displayedMemory: MemorySnapshot = memory.kind === "split" ? { kind: "unified", ...memory.ram, metalOwner: null, gpuUtilizationPercent: memory.gpuUtilizationPercent, sampledAt: memory.sampledAt } : memory;
  const vram = memory.kind === "split" ? memory.vram : null;
  const vramUsed = vram?.totalBytes != null && vram.availableBytes != null ? vram.totalBytes - vram.availableBytes : null;
  const resetUsage = () => {
    void api
      .resetLlmSessionUsage()
      .then(setUsage)
      .catch(() => undefined);
  };
  useEffect(() => {
    let disposed = false;
    let refreshingMemory = false;
    let refreshingUsage = false;
    let resourceTimer: number | undefined;
    let usageTimer: number | undefined;
    let initialTimer: number | undefined;
    let initialRefreshUntil = 0;
    const refreshMemory = async () => {
      if (document.visibilityState === "hidden" || refreshingMemory) return;
      refreshingMemory = true;
      let needsFollowup = true;
      try {
        const value = await api.memorySnapshot();
        if (disposed) return;
        needsFollowup = memoryNeedsInitialFollowup(value);
        setMemory((current) => stabilizeMemorySnapshot(current, value));
        setGpu((current) => updateGpuUtilization(current, value.gpuUtilizationPercent, value.sampledAt));
      } catch {
        // Keep the last successful sample while the local API is starting.
      } finally {
        refreshingMemory = false;
        if (!disposed && needsFollowup && performance.now() < initialRefreshUntil) {
          if (initialTimer !== undefined) window.clearTimeout(initialTimer);
          initialTimer = window.setTimeout(() => void refreshMemory(), INITIAL_REFRESH_INTERVAL_MS);
        }
      }
    };
    const refreshUsage = async () => {
      if (document.visibilityState === "hidden" || refreshingUsage) return;
      refreshingUsage = true;
      try {
        const value = await api.llmSessionUsage();
        if (!disposed) setUsage(value);
      } catch {
        // Usage is optional and must not hold up resource meters.
      } finally {
        refreshingUsage = false;
      }
    };
    const updatePolling = () => {
      if (resourceTimer !== undefined) window.clearInterval(resourceTimer);
      if (usageTimer !== undefined) window.clearInterval(usageTimer);
      if (initialTimer !== undefined) window.clearTimeout(initialTimer);
      resourceTimer = undefined;
      usageTimer = undefined;
      initialTimer = undefined;
      if (document.visibilityState !== "hidden") {
        initialRefreshUntil = performance.now() + INITIAL_REFRESH_WINDOW_MS;
        setGpu(discardGpuSamples);
        void refreshMemory();
        void refreshUsage();
        resourceTimer = window.setInterval(() => void refreshMemory(), RESOURCE_REFRESH_INTERVAL_MS);
        usageTimer = window.setInterval(() => void refreshUsage(), USAGE_REFRESH_INTERVAL_MS);
      }
    };
    updatePolling();
    document.addEventListener("visibilitychange", updatePolling);
    window.addEventListener("scena-llm-usage-reset", refreshUsage);
    return () => {
      disposed = true;
      if (resourceTimer !== undefined) window.clearInterval(resourceTimer);
      if (usageTimer !== undefined) window.clearInterval(usageTimer);
      if (initialTimer !== undefined) window.clearTimeout(initialTimer);
      document.removeEventListener("visibilitychange", updatePolling);
      window.removeEventListener("scena-llm-usage-reset", refreshUsage);
    };
  }, []);

  return (
    <footer className="main-window-footer">
      <div className="main-window-meters">
        <MemoryMeter memory={displayedMemory} />
        <GpuMemoryMeter used={vramUsed} total={vram?.totalBytes} other={vram?.otherUsedBytes} llm={vram?.llmBytes} tts={vram?.ttsBytes} />
        <GpuMeter percent={gpu.displayedPercent} />
      </div>
      <nav className="main-window-footer-menu" aria-label="アプリケーションメニュー">
        <TokenUsageMenu usage={usage} onReset={resetUsage} />
        <ExpressionPaletteMenu onInsertEmoji={onInsertEmoji} />

        <div className="main-window-footer-item main-window-shortcut-menu">
          <button type="button" aria-label="ショートカット">
            {!isWindows() && <span aria-hidden="true">⌘</span>}
            <span>ショートカット</span>
          </button>
          <div className="main-window-footer-submenu main-window-shortcut-submenu" aria-label="ショートカットメニュー">
            <ShortcutReference />
          </div>
        </div>

        <VersionMenu />
        <MasterAudioControls />
      </nav>
    </footer>
  );
}
