import type { LoraMix, LoraMixEntry, LoraReference } from "../../types/project";
export function effectiveMix(item: { loraMix?: LoraMix | null; lora?: LoraReference | null }): LoraMix {
  if (item.loraMix) return item.loraMix;
  if (!item.lora) return { version: 1, baseWeight: 10000, entries: [] };
  const { enabled, ...identity } = item.lora;
  return { version: 1, baseWeight: enabled ? 0 : 10000, entries: [{ ...identity, weight: enabled ? 10000 : 0 }] };
}
export const mixWeights = (mix: LoraMix) => [mix.baseWeight, ...mix.entries.map((entry) => entry.weight)];
export function withWeights(mix: LoraMix, weights: number[]): LoraMix {
  return { ...mix, baseWeight: weights[0], entries: mix.entries.map((entry, index) => ({ ...entry, weight: weights[index + 1] })) };
}
/** Largest remainders, stable display-order ties; integer arithmetic throughout. */
export function apportion(total: number, ratios: number[]): number[] {
  const sum = ratios.reduce((a, b) => a + b, 0);
  if (!sum) return ratios.map((_, index) => (index === 0 ? total : 0));
  const amounts = ratios.map((ratio) => Math.floor((total * ratio) / sum));
  const order = ratios.map((ratio, index) => ({ index, remainder: (total * ratio) % sum })).sort((a, b) => b.remainder - a.remainder || a.index - b.index);
  const remainder = total - amounts.reduce((a, b) => a + b, 0);
  for (let index = 0; index < remainder; index++) amounts[order[index].index]++;
  return amounts;
}
export function addMixEntry(mix: LoraMix, entry: Omit<LoraMixEntry, "weight">): LoraMix {
  if (mix.entries.length >= 4 || mix.entries.some((item) => item.assetId === entry.assetId)) return mix;
  const next = { ...mix, entries: [...mix.entries, { ...entry, weight: 0 }] };
  return withWeights(next, apportion(10000, Array(next.entries.length + 1).fill(1)));
}
export function removeMixEntry(mix: LoraMix, assetId: string): LoraMix {
  const removed = mix.entries.find((item) => item.assetId === assetId);
  return { ...mix, baseWeight: mix.baseWeight + (removed?.weight ?? 0), entries: mix.entries.filter((item) => item.assetId !== assetId) };
}
export const MIN_MIX_WEIGHT = 1000;
/** Repair legacy zero/small shares only in the editor draft, preserving donor ratios. */
export function editableMix(mix: LoraMix): LoraMix {
  const weights = mixWeights(mix);
  const deficit = weights.reduce((sum, weight) => sum + Math.max(0, MIN_MIX_WEIGHT - weight), 0);
  if (!deficit) return mix;
  const donations = apportion(
    deficit,
    weights.map((weight) => Math.max(0, weight - MIN_MIX_WEIGHT)),
  );
  return withWeights(
    mix,
    weights.map((weight, index) => Math.max(MIN_MIX_WEIGHT, weight) - donations[index]),
  );
}
export function moveMixBoundary(mix: LoraMix, index: number, left: number): LoraMix {
  const draft = editableMix(mix);
  const weights = mixWeights(draft);
  const total = weights[index] + weights[index + 1];
  weights[index] = Math.max(MIN_MIX_WEIGHT, Math.min(total - MIN_MIX_WEIGHT, Math.round(left)));
  weights[index + 1] = total - weights[index];
  return withWeights(draft, weights);
}

/** Redistribute the remaining slack above the ten-percent floor. */
export function specifyMixWeight(mix: LoraMix, index: number, weight: number): LoraMix {
  const weights = mixWeights(editableMix(mix));
  const others = weights.filter((_, position) => position !== index);
  const remaining = apportion(
    10000 - weight - others.length * MIN_MIX_WEIGHT,
    others.map((value) => value - MIN_MIX_WEIGHT),
  );
  let cursor = 0;
  return withWeights(
    mix,
    weights.map((_, position) => (position === index ? weight : MIN_MIX_WEIGHT + remaining[cursor++])),
  );
}

export function parseMixWeight(draft: string, count: number): { weight?: number; error: string } {
  const minimum = count ? 10 : 100;
  const maximum = 100 - count * 10;
  const weight = Math.round(Number(draft) * 100);
  if (!/^\d+(?:\.\d{1,2})?$/.test(draft) || weight < minimum * 100 || weight > maximum * 100) return { error: `${minimum}〜${maximum}%を、小数点以下2桁までで指定してください。` };
  return { weight, error: "" };
}
