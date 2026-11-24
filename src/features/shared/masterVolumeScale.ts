import { MASTER_MAX_DB, MASTER_MIN_DB, type MasterVolumeDb } from "./audioEngine";

export const formatMasterVolume = (value: MasterVolumeDb) => {
  if (value === null) return "−∞ dB";
  const formatted = Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1);
  return `${value > 0 ? "+" : ""}${formatted} dB`;
};

export function masterVolumeAngle(value: MasterVolumeDb) {
  if (value === null) return -120;
  const clamped = Math.max(MASTER_MIN_DB, Math.min(MASTER_MAX_DB, value));
  if (clamped > 0) return (clamped / MASTER_MAX_DB) * 120;
  const negativePosition = 0.04 + 0.96 * (1 - Math.sqrt(-clamped / -MASTER_MIN_DB));
  return -120 + negativePosition * 120;
}

export function stepMasterVolume(value: MasterVolumeDb, direction: -1 | 1): MasterVolumeDb {
  if (value === null) return direction > 0 ? MASTER_MIN_DB : null;
  if (direction < 0 && value <= MASTER_MIN_DB) return null;
  const size = direction > 0 ? (value < -30 ? 1 : value < -10 ? 0.5 : 0.1) : value > -10 ? 0.1 : value > -30 ? 0.5 : 1;
  return Math.max(MASTER_MIN_DB, Math.min(MASTER_MAX_DB, Math.round((value + size * direction) * 10) / 10));
}

export function adjustMasterVolume(value: MasterVolumeDb, steps: number) {
  let next = value;
  const direction = steps < 0 ? -1 : 1;
  for (let index = 0; index < Math.abs(steps); index += 1) next = stepMasterVolume(next, direction);
  return next;
}
