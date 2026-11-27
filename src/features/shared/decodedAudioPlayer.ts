import { apiFetch } from "../../api-runtime";
import { audioEngine } from "./audioEngine";

const START_DELAY_SECONDS = 0.02;

export type DecodedAudioPlaybackControl = {
  stop: () => void;
};

type PlayerCallbacks = {
  onDuration?: (duration: number) => void;
  onTime?: (currentTime: number) => void;
  onPlay?: (player: DecodedAudioPlaybackControl) => void;
  onPause?: (player: DecodedAudioPlaybackControl) => void;
  onEnded?: (player: DecodedAudioPlaybackControl) => void;
  onError?: (error: unknown) => void;
};

export class DecodedAudioPlayer implements DecodedAudioPlaybackControl {
  private callbacks: PlayerCallbacks;
  private source: AudioBufferSourceNode | null = null;
  private context: AudioContext | null = null;
  private buffer: AudioBuffer | null = null;
  private loadPromise: Promise<boolean> = Promise.resolve(false);
  private loadToken = 0;
  private playGeneration = 0;
  private frame: number | undefined;
  private offset = 0;
  private startOffset = 0;
  private scheduledStart = 0;
  private desiredPlaying = false;
  private playing = false;
  private meterActive = false;

  constructor(callbacks: PlayerCallbacks = {}) {
    this.callbacks = callbacks;
  }

  setCallbacks(callbacks: PlayerCallbacks) {
    this.callbacks = callbacks;
  }

  setSource(url: string) {
    this.stop();
    this.playGeneration += 1;
    const token = ++this.loadToken;
    this.buffer = null;
    this.context = null;
    this.offset = 0;
    this.callbacks.onDuration?.(0);
    this.callbacks.onTime?.(0);
    this.loadPromise = url ? this.load(url, token) : Promise.resolve(false);
    return this.loadPromise;
  }

  async play() {
    this.desiredPlaying = true;
    const token = this.loadToken;
    const generation = ++this.playGeneration;
    if (!(await this.loadPromise) || this.isStalePlay(generation, token)) return;
    try {
      const { context, source } = await audioEngine.createBufferSource();
      if (this.isStalePlay(generation, token) || !this.buffer) {
        source.disconnect();
        return;
      }
      this.context = context;
      source.buffer = this.buffer;
      this.source = source;
      if (this.offset >= this.buffer.duration) {
        this.offset = 0;
        this.callbacks.onTime?.(0);
      }
      this.startOffset = this.offset;
      this.scheduledStart = context.currentTime + START_DELAY_SECONDS;
      source.onended = () => this.finishNaturally(source);
      this.playing = true;
      this.setMeterActive(true);
      this.callbacks.onPlay?.(this);
      source.start(this.scheduledStart, this.startOffset);
      this.updateTime();
    } catch (error) {
      if (token === this.loadToken && generation === this.playGeneration) this.fail(error);
    }
  }

  private isStalePlay(generation: number, token: number) {
    return generation !== this.playGeneration || !this.desiredPlaying || token !== this.loadToken || !this.buffer;
  }

  toggle() {
    if (this.desiredPlaying || this.playing) this.pause();
    else void this.play();
  }

  pause() {
    const wasActive = this.desiredPlaying || this.playing;
    this.playGeneration += 1;
    this.desiredPlaying = false;
    this.captureOffset();
    this.haltSource();
    if (wasActive) this.callbacks.onPause?.(this);
  }

  stop() {
    const wasActive = this.desiredPlaying || this.playing;
    this.playGeneration += 1;
    this.desiredPlaying = false;
    this.haltSource();
    this.offset = 0;
    this.callbacks.onTime?.(0);
    if (wasActive) this.callbacks.onPause?.(this);
  }

  seek(seconds: number) {
    const duration = this.buffer?.duration ?? 0;
    const next = Math.max(0, Math.min(duration, seconds));
    const resume = this.desiredPlaying || this.playing;
    this.playGeneration += 1;
    this.desiredPlaying = false;
    this.haltSource();
    this.offset = next;
    this.callbacks.onTime?.(next);
    if (resume) void this.play();
  }

  dispose() {
    this.loadToken += 1;
    this.playGeneration += 1;
    this.callbacks = {};
    this.stop();
    this.buffer = null;
    this.context = null;
  }

  private async load(url: string, token: number) {
    try {
      const response = await apiFetch(url, { cache: "force-cache" });
      if (!response.ok) throw new Error(`音声を読み込めませんでした (${response.status})`);
      const bytes = await response.arrayBuffer();
      const { context, buffer } = await audioEngine.decodeAudioData(bytes);
      if (token !== this.loadToken) return false;
      this.context = context;
      this.buffer = buffer;
      this.callbacks.onDuration?.(buffer.duration);
      return true;
    } catch (error) {
      if (token === this.loadToken) this.fail(error);
      return false;
    }
  }

  private captureOffset() {
    if (!this.playing || !this.context || !this.buffer) return;
    const elapsed = Math.max(0, this.context.currentTime - this.scheduledStart);
    this.offset = Math.min(this.buffer.duration, this.startOffset + elapsed);
  }

  private haltSource() {
    if (this.frame !== undefined) cancelAnimationFrame(this.frame);
    this.frame = undefined;
    const source = this.source;
    this.source = null;
    this.playing = false;
    if (source) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        /* already ended */
      }
    }
    this.setMeterActive(false);
  }

  private finishNaturally(source: AudioBufferSourceNode) {
    if (this.source !== source) return;
    this.source = null;
    this.desiredPlaying = false;
    this.playing = false;
    this.offset = this.buffer?.duration ?? 0;
    if (this.frame !== undefined) cancelAnimationFrame(this.frame);
    this.frame = undefined;
    this.setMeterActive(false);
    this.callbacks.onTime?.(this.offset);
    this.callbacks.onEnded?.(this);
  }

  private updateTime = () => {
    if (!this.playing || !this.context || !this.buffer) return;
    const elapsed = Math.max(0, this.context.currentTime - this.scheduledStart);
    this.callbacks.onTime?.(Math.min(this.buffer.duration, this.startOffset + elapsed));
    this.frame = requestAnimationFrame(this.updateTime);
  };

  private setMeterActive(active: boolean) {
    if (this.meterActive === active) return;
    this.meterActive = active;
    audioEngine.setBufferPlaybackActive(active);
  }

  private fail(error: unknown) {
    this.desiredPlaying = false;
    this.haltSource();
    this.callbacks.onError?.(error);
  }
}
