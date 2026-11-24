import { apiFetch } from "../../api-runtime";
import { audioEngine } from "../shared/audioEngine";
import type { TimelineInterval } from "./timelineApi";

export class TimelinePlaybackAudio {
  private context?: AudioContext;
  private sources = new Set<AudioBufferSourceNode>();
  private buffers = new Map<string, AudioBuffer>();
  private pending = new Map<string, Promise<void>>();
  private scheduled: Array<{ interval: TimelineInterval; when: number; until: number }> = [];
  private clockEnd = 0;
  private closed = false;
  private metering = false;

  async prepare(interval: TimelineInterval, signal: AbortSignal) {
    if (interval.status !== "ready" || !interval.audioUrl || this.buffers.has(interval.intervalId)) return;
    const existing = this.pending.get(interval.intervalId);
    if (existing) return existing;
    const pending = (async () => {
      const response = await apiFetch(interval.audioUrl!, { signal });
      if (!response.ok) throw new Error(`Timeline audio HTTP ${response.status}`);
      const { context, buffer } = await audioEngine.decodeAudioData(await response.arrayBuffer());
      if (signal.aborted || this.closed) return;
      this.context = context;
      this.buffers.set(interval.intervalId, buffer);
    })();
    this.pending.set(interval.intervalId, pending);
    try {
      await pending;
    } finally {
      this.pending.delete(interval.intervalId);
    }
  }

  async schedule(interval: TimelineInterval) {
    if (this.closed || (interval.status !== "ready" && interval.status !== "silence")) return false;
    const routed = await audioEngine.createBufferSource();
    if (this.closed) {
      routed.source.disconnect();
      return false;
    }
    this.context = routed.context;
    const buffer = this.buffers.get(interval.intervalId);
    if (interval.status !== "silence" && !buffer) {
      routed.source.disconnect();
      return false;
    }
    const when = Math.max(this.clockEnd, this.context.currentTime + (this.clockEnd > this.context.currentTime ? 0 : 0.02));
    const until = when + (interval.endFrame - interval.startFrame) / interval.sampleRate;
    if (buffer) {
      routed.source.buffer = buffer;
      this.sources.add(routed.source);
      routed.source.onended = () => {
        this.sources.delete(routed.source);
        routed.source.disconnect();
      };
      routed.source.start(when);
    } else routed.source.disconnect();
    this.clockEnd = until;
    this.scheduled.push({ interval, when, until });
    this.buffers.delete(interval.intervalId);
    if (!this.metering) audioEngine.setBufferPlaybackActive(true);
    this.metering = true;
    return true;
  }

  activeIds() {
    const now = this.context?.currentTime ?? 0;
    this.scheduled = this.scheduled.filter((item) => item.until > now);
    const active = this.scheduled.find((item) => item.when <= now && now < item.until);
    if (!active) return [];
    const frame = active.interval.startFrame + (now - active.when) * active.interval.sampleRate;
    return active.interval.events
      .filter((event) => event.startFrame <= frame && frame < event.endFrame)
      .sort((a, b) => b.startFrame - a.startFrame)
      .map((event) => event.lineId);
  }

  aheadSeconds() {
    return Math.max(0, this.clockEnd - (this.context?.currentTime ?? 0));
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    this.sources.forEach((source) => {
      try {
        source.stop();
      } catch {
        /* already ended */
      }
      source.disconnect();
    });
    this.sources.clear();
    this.buffers.clear();
    this.scheduled = [];
    if (this.metering) audioEngine.setBufferPlaybackActive(false);
    this.metering = false;
  }
}
