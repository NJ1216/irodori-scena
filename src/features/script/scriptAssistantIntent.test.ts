import { describe, expect, it } from "vitest";
import { explicitlyRequestsSimultaneousSpeech, minimumLinesForSimultaneousSpeech } from "./scriptAssistantIntent";

describe("script assistant simultaneous intent", () => {
  it.each(["同時発話の挨拶から始める", "動時発話の挨拶から始まる感じで", "二人が同時に返事をする", "声を重ねて笑う"])("recognizes an explicit request: %s", (instruction) => {
    expect(explicitlyRequestsSimultaneousSpeech(instruction)).toBe(true);
  });

  it.each(["自然な挨拶にする", "同時発話は不要", "同時発話を避ける"])("does not require simultaneous speech: %s", (instruction) => expect(explicitlyRequestsSimultaneousSpeech(instruction)).toBe(false));

  it("reserves a lead-in line before a requested simultaneous exchange", () => {
    expect(minimumLinesForSimultaneousSpeech("片方の掛け声で、動時発話の挨拶から始める")).toBe(3);
    expect(minimumLinesForSimultaneousSpeech("二人が同時発話で挨拶する")).toBe(2);
  });
});
