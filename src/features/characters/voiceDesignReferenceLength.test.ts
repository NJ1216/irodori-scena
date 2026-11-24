import { expect, it } from "vitest";
import { referenceOverflowSeconds } from "./voiceDesignReferenceLength";

const clip = (id: string, durationSeconds?: number) => ({ id, durationSeconds });

it("is zero when the joined clips fit in the 120-second reference", () => {
  const candidates = [clip("b", 15), ...["n", "j", "a", "s", "d"].map((id) => clip(id, 15))];
  expect(referenceOverflowSeconds(candidates, "b", { normal: "n", joy: "j", anger: "a", sorrow: "s", delight: "d" })).toBe(0);
});

it("counts the 0.7-second gaps and reports the seconds cut from the end", () => {
  const candidates = [clip("b", 30), ...["n", "j", "a", "s", "d"].map((id) => clip(id, 30))];
  expect(referenceOverflowSeconds(candidates, "b", { normal: "n", joy: "j", anger: "a", sorrow: "s", delight: "d" })).toBeCloseTo(63.5);
});

it("ignores unselected or unknown clips and clips without a duration", () => {
  const candidates = [clip("b", 100), clip("n", 25), clip("j")];
  expect(referenceOverflowSeconds(candidates, "b", { normal: "n", joy: "j", anger: "missing" })).toBeCloseTo(5.7);
  expect(referenceOverflowSeconds(candidates, null, { normal: "n" })).toBe(0);
});
