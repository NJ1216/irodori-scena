export const MASTER_VOLUME_KEY = "scena-master-volume-db";
export const MASTER_MIN_DB = -60;
export const MASTER_MAX_DB = 6;
export type MasterVolumeDb = number | null;
export type StereoLevel = { left: number; right: number; leftSamplePeak: number; rightSamplePeak: number; leftPeak: number; rightPeak: number; active: boolean };

const silentLevel: StereoLevel = { left: -60, right: -60, leftSamplePeak: -60, rightSamplePeak: -60, leftPeak: -60, rightPeak: -60, active: false };
export function dbToGain(db: MasterVolumeDb) {
  return db === null ? 0 : 10 ** (Math.max(MASTER_MIN_DB, Math.min(MASTER_MAX_DB, db)) / 20);
}

export function restoreMasterVolume(storage: Pick<Storage, "getItem"> = localStorage): MasterVolumeDb {
  const raw = storage.getItem(MASTER_VOLUME_KEY);
  if (raw === "-Infinity") return null;
  if (raw === null) return 0;
  const value = Number(raw);
  return Number.isFinite(value) && value >= MASTER_MIN_DB && value <= MASTER_MAX_DB ? value : 0;
}

export function rmsDb(samples: Float32Array) {
  if (!samples.length) return -60;
  const sum = samples.reduce((total, sample) => total + sample * sample, 0);
  return Math.max(MASTER_MIN_DB, Math.min(MASTER_MAX_DB, 20 * Math.log10(Math.sqrt(sum / samples.length) || 0.001)));
}

export function samplePeakDb(samples: Float32Array) {
  const peak = samples.reduce((maximum, sample) => Math.max(maximum, Math.abs(sample)), 0);
  return Math.max(MASTER_MIN_DB, Math.min(MASTER_MAX_DB, 20 * Math.log10(peak || 0.001)));
}

export class AudioEngine {
  private context?: AudioContext;
  private bus?: GainNode;
  private master?: GainNode;
  private analysers?: [AnalyserNode, AnalyserNode];
  private retirement?: ReturnType<typeof setTimeout>;
  private volume = typeof localStorage === "undefined" ? 0 : restoreMasterVolume();
  private volumeListeners = new Set<(value: MasterVolumeDb) => void>();
  private levelListeners = new Set<(value: StereoLevel) => void>();
  private activeSources = 0;
  private preparing = 0;
  private frame?: number;
  private peaks = [-60, -60];
  private peakTimes = [0, 0];

  private ensure() {
    if (this.retirement !== undefined) {
      clearTimeout(this.retirement);
      this.retirement = undefined;
    }
    if (this.context?.state === "closed") this.releaseContext(this.context);
    if (this.context) return this.context;
    const context = new AudioContext();
    const bus = context.createGain();
    const master = context.createGain();
    const splitter = context.createChannelSplitter(2);
    const merger = context.createChannelMerger(2);
    const left = context.createAnalyser();
    const right = context.createAnalyser();
    bus.channelCount = 2;
    bus.channelCountMode = "explicit";
    bus.channelInterpretation = "speakers";
    left.fftSize = right.fftSize = 1024;
    bus.connect(master);
    master.connect(splitter);
    splitter.connect(left, 0, 0);
    splitter.connect(right, 1, 0);
    left.connect(merger, 0, 0);
    right.connect(merger, 0, 1);
    merger.connect(context.destination);
    master.gain.value = dbToGain(this.volume);
    this.context = context;
    this.bus = bus;
    this.master = master;
    this.analysers = [left, right];
    return context;
  }

  private releaseContext(context: AudioContext) {
    if (this.context !== context) return;
    this.context = undefined;
    this.bus = undefined;
    this.master = undefined;
    this.analysers = undefined;
  }

  private retireContextWhenIdle() {
    if (this.retirement !== undefined) clearTimeout(this.retirement);
    const context = this.context;
    if (!context || this.preparing || this.activeSources) return;
    this.retirement = setTimeout(() => {
      this.retirement = undefined;
      if (this.activeSources || this.preparing || this.context !== context) return;
      this.releaseContext(context);
      void context.close().catch(() => undefined);
    }, 0);
  }

  private async resume(context: AudioContext) {
    if (context.state !== "running") await context.resume();
  }

  getVolume() {
    return this.volume;
  }

  setVolume(value: MasterVolumeDb) {
    this.volume = value === null ? null : Math.max(MASTER_MIN_DB, Math.min(MASTER_MAX_DB, value));
    if (this.master) this.master.gain.value = dbToGain(this.volume);
    localStorage.setItem(MASTER_VOLUME_KEY, this.volume === null ? "-Infinity" : String(this.volume));
    this.volumeListeners.forEach((listener) => listener(this.volume));
  }

  subscribeVolume(listener: (value: MasterVolumeDb) => void) {
    this.volumeListeners.add(listener);
    listener(this.volume);
    return () => void this.volumeListeners.delete(listener);
  }

  subscribeLevels(listener: (value: StereoLevel) => void) {
    this.levelListeners.add(listener);
    listener(this.activeSources ? { ...silentLevel, active: true } : silentLevel);
    return () => void this.levelListeners.delete(listener);
  }

  private async prepare<T>(action: (context: AudioContext) => Promise<T>): Promise<T> {
    this.preparing++;
    try {
      const context = this.ensure();
      await this.resume(context);
      return await action(context);
    } finally {
      this.preparing--;
      // Predecoding alone must not leave an idle WebKit output alive across sleep.
      // Defer until callers can activate a newly prepared source in this turn.
      this.retireContextWhenIdle();
    }
  }

  async decodeAudioData(data: ArrayBuffer) {
    return this.prepare(async (context) => ({ context, buffer: await context.decodeAudioData(data) }));
  }

  async createBufferSource() {
    return this.prepare(async (context) => {
      const source = context.createBufferSource();
      source.connect(this.bus!);
      return { context, source };
    });
  }

  connectNode(node: AudioNode) {
    this.ensure();
    node.connect(this.bus!);
  }

  setBufferPlaybackActive(active: boolean) {
    this.markActive(active);
  }

  private markActive(start: boolean) {
    this.activeSources = Math.max(0, this.activeSources + (start ? 1 : -1));
    if (this.activeSources && this.frame === undefined) {
      if (this.retirement !== undefined) clearTimeout(this.retirement);
      this.retirement = undefined;
      this.sample();
    }
    if (!this.activeSources) {
      if (this.frame !== undefined) cancelAnimationFrame(this.frame);
      this.frame = undefined;
      this.peaks = [-60, -60];
      this.levelListeners.forEach((listener) => listener(silentLevel));
      this.retireContextWhenIdle();
    }
  }

  private sample = () => {
    if (!this.activeSources || !this.analysers) return;
    const now = performance.now();
    const measurements = this.analysers.map((analyser, channel) => {
      const samples = new Float32Array(analyser.fftSize);
      analyser.getFloatTimeDomainData(samples);
      const level = rmsDb(samples);
      const samplePeak = samplePeakDb(samples);
      if (samplePeak >= this.peaks[channel]) {
        this.peaks[channel] = samplePeak;
        this.peakTimes[channel] = now;
      } else if (now - this.peakTimes[channel] > 1000) this.peaks[channel] = Math.max(samplePeak, this.peaks[channel] - 1.2);
      return { level, samplePeak };
    });
    this.levelListeners.forEach((listener) => listener({ left: measurements[0].level, right: measurements[1].level, leftSamplePeak: measurements[0].samplePeak, rightSamplePeak: measurements[1].samplePeak, leftPeak: this.peaks[0], rightPeak: this.peaks[1], active: true }));
    this.frame = requestAnimationFrame(this.sample);
  };
}

export const audioEngine = new AudioEngine();
