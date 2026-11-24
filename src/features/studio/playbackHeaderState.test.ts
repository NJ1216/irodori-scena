import { describe, expect, it } from "vitest";
import { disablePlaybackToggle, playbackToggleActive } from "./playbackHeaderState";

describe("playback header state", () => {
  it("does not turn the continuous-playback button into Stop for line preview playback", () => {
    expect(playbackToggleActive(false)).toBe(false);
  });

  it("shows Stop only while continuous playback itself is active", () => {
    expect(playbackToggleActive(true)).toBe(true);
  });

  it("allows continuous playback on the script tab during another non-draft operation", () => {
    expect(disablePlaybackToggle("script", "generate-selected-lines", false)).toBe(false);
  });
});
