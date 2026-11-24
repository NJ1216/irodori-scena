import { expect, it } from "vitest";
import { addMixEntry, apportion, effectiveMix, mixWeights, moveMixBoundary, removeMixEntry, editableMix } from "./loraMix";
const entry = { assetId: "one", adapterHash: "hash", baseModelRepo: "base", baseModelRevision: "revision" };
const base = effectiveMix({});
it("adds evenly with stable largest remainders, limits to four and disallows duplicates", () => {
  let mix = addMixEntry(base, entry);
  expect(mixWeights(mix)).toEqual([5000, 5000]);
  mix = addMixEntry(mix, { ...entry, assetId: "two" });
  expect(mixWeights(mix)).toEqual([3334, 3333, 3333]);
  expect(addMixEntry(mix, entry)).toBe(mix);
  mix = addMixEntry(addMixEntry(mix, { ...entry, assetId: "three" }), { ...entry, assetId: "four" });
  expect(mixWeights(mix)).toEqual([2000, 2000, 2000, 2000, 2000]);
  expect(addMixEntry(mix, { ...entry, assetId: "five" })).toBe(mix);
});
it("removal returns only the removed share to base", () => {
  const mix = {
    ...base,
    baseWeight: 2000,
    entries: [
      { ...entry, weight: 3000 },
      { ...entry, assetId: "two", weight: 5000 },
    ],
  };
  expect(mixWeights(removeMixEntry(mix, "one"))).toEqual([5000, 5000]);
});
it("normalizes zero and small legacy shares only in drafts and preserves exact total", () => {
  const saved = { ...base, baseWeight: 10000, entries: Array.from({ length: 4 }, (_, index) => ({ ...entry, assetId: String(index), weight: 0 })) };
  const draft = editableMix(saved);
  expect(mixWeights(draft)).toEqual([6000, 1000, 1000, 1000, 1000]);
  expect(saved.baseWeight).toBe(10000);
  expect(saved.entries.every((item) => item.weight === 0)).toBe(true);
  expect(editableMix(draft)).toBe(draft);
  const partial = {
    ...base,
    baseWeight: 500,
    entries: [
      { ...entry, weight: 2500 },
      { ...entry, assetId: "two", weight: 7000 },
    ],
  };
  expect(mixWeights(editableMix(partial))).toEqual([1000, 2400, 6600]);
  expect(apportion(3, [1, 1, 1, 1])).toEqual([1, 1, 1, 0]);
});
it("boundaries only affect neighbors and both remain at least ten percent", () => {
  const mix = addMixEntry(addMixEntry(base, entry), { ...entry, assetId: "two" });
  expect(mixWeights(moveMixBoundary(mix, 1, 10000))).toEqual([3334, 5666, 1000]);
  expect(mixWeights(moveMixBoundary(mix, 0, -1))).toEqual([1000, 5667, 3333]);
});
it("legacy storage retains its original endpoints while editor drafts keep every segment", () => {
  const item = { lora: { ...entry, enabled: false } };
  expect(mixWeights(effectiveMix(item))).toEqual([10000, 0]);
  expect(mixWeights(editableMix(effectiveMix(item)))).toEqual([9000, 1000]);
  expect(item).not.toHaveProperty("loraMix");
  expect(mixWeights(effectiveMix({ lora: { ...entry, enabled: true } }))).toEqual([0, 10000]);
  expect(mixWeights(editableMix(effectiveMix({ lora: { ...entry, enabled: true } })))).toEqual([1000, 9000]);
});

it("direct percentage keeps every other share above the floor and the exact total", async () => {
  const { specifyMixWeight } = await import("./loraMix");
  const mix = { version: 1 as const, baseWeight: 4000, entries: [0, 1, 2].map((index) => ({ assetId: String(index), adapterHash: "hash", baseModelRepo: "base", baseModelRevision: "rev", weight: 2000 })) };
  const next = specifyMixWeight(mix, 1, 7000);
  expect(next.baseWeight).toBe(1000);
  expect(next.entries.map((entry) => entry.weight)).toEqual([7000, 1000, 1000]);
  expect(mix.baseWeight).toBe(4000);
});
