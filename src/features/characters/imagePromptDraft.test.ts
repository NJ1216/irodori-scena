import { describe, expect, it } from "vitest";
import { emptyImagePromptDraft, imagePromptDraftFromPreferences, imagePromptPreferencesFromDraft } from "./imagePromptDraft";

describe("image prompt draft", () => {
  it("creates empty preferences without inventing values", () => {
    expect(imagePromptPreferencesFromDraft(emptyImagePromptDraft())).toMatchObject({ output_language: "english", subject: "", gestures: [] });
  });

  it("round-trips saved preferences and limits gestures to one", () => {
    const saved = { ...imagePromptPreferencesFromDraft(emptyImagePromptDraft()), subject: "1girl", hair_color: "red", accessory: "ティアラ, 王冠", facial_hair: "口ひげ, あごひげ", makeup: "華やか", gestures: ["wave", "point"] };
    const draft = imagePromptDraftFromPreferences(saved);
    expect(draft.gestures).toEqual(["wave"]);
    expect(draft.accessory).toEqual(["ティアラ", "王冠"]);
    expect(draft.facial_hair).toEqual(["口ひげ", "あごひげ"]);
    expect(imagePromptPreferencesFromDraft(draft)).toEqual({ ...saved, makeup: "", gestures: ["wave"] });
  });
});
