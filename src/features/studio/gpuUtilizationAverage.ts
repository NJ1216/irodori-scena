export type GpuSample = { value: number; sampledAt: number };

export type GpuUtilizationState = {
  samples: GpuSample[];
  displayedPercent: number | null;
};

export const emptyGpuUtilizationState: GpuUtilizationState = { samples: [], displayedPercent: null };

export function updateGpuUtilization(state: GpuUtilizationState, value: number | null, sampledAt: number): GpuUtilizationState {
  const recent = state.samples.filter((sample) => sampledAt - sample.sampledAt <= 3000);
  const samples = value == null ? recent : [...recent, { value, sampledAt }].slice(-3);
  if (value == null) return { samples, displayedPercent: state.displayedPercent };
  return {
    samples,
    displayedPercent: Math.max(...samples.map((sample) => sample.value)),
  };
}

export function discardGpuSamples(state: GpuUtilizationState): GpuUtilizationState {
  return { ...state, samples: [] };
}
