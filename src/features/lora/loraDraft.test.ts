import { describe, expect, it } from "vitest";
import { inputProblems, parseTrainingLimits, parseTrainingSettings } from "./loraDraft";
import type { LoraInputRow } from "../../types/lora";
const row = (id: string): LoraInputRow => ({ id, wavName: `${id}.wav`, textName: `${id}.txt`, text: "こんにちは。", caption: "", speakerId: "one", durationSeconds: 2, issues: [] });
describe("training acceptance", () => {
  it("allows empty captions and manual transcripts for missing TXT", () => {
    expect(inputProblems([row("a"), { ...row("b"), textName: null, issues: ["TXT がありません。本文を入力してください。"] }])).toEqual([]);
  });
  it("requires two valid pairs and refuses missing WAV, blank text, speaker and invalid audio", () => {
    expect(inputProblems([row("a")])[0]).toContain("2組");
    expect(inputProblems([{ ...row("a"), wavName: null }, row("b")])[0]).toContain("WAV");
    expect(inputProblems([{ ...row("a"), text: " " }, row("b")])[0]).toContain("本文");
    expect(inputProblems([{ ...row("a"), speakerId: " " }, row("b")])[0]).toContain("話者ID");
    expect(inputProblems([{ ...row("a"), issues: ["PCM WAV として読めません。"] }, row("b")])[0]).toContain("PCM");
  });
  it("validates numeric drafts only at commit without completing partial input", () => {
    for (const draft of ["", "-", "1.", "1.5", "0", "100001"]) expect(() => parseTrainingSettings(draft, "0.0001")).toThrow();
    for (const draft of ["", "-", ".", "1e", "Infinity", "0x1", "0", "0.1"]) expect(() => parseTrainingSettings("3", draft)).toThrow();
    expect(parseTrainingSettings("3", "1e-4")).toEqual({ maxSteps: 3, learningRate: 0.0001 });
  });
});

it("validates batch and input duration drafts at start without clamping", () => {
  expect(parseTrainingLimits("1", "")).toEqual({ batchSize: 1, maxSeconds: null });
  expect(parseTrainingLimits("1", "30")).toEqual({ batchSize: 1, maxSeconds: 30 });
  for (const draft of ["", "-", "0", "5", "1.5"]) expect(() => parseTrainingLimits(draft, "30")).toThrow();
  for (const draft of ["-", ".", "0", "121"]) expect(() => parseTrainingLimits("1", draft)).toThrow();
});
