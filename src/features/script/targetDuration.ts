export function normalizeTargetDuration(value: number) {
  return Math.round(Math.max(0.5, Math.min(30, value)) * 10) / 10;
}
