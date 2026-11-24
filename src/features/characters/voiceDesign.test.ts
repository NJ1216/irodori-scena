import { describe, expect, it } from "vitest";
import { emptyVoiceDesign, hasVoiceDesignInput, normalizeVoiceDesign, voiceDesignAges, voiceDesignGenders, voiceDesignKeywords, voiceDesignQualities } from "./voiceDesign";
import { mergeVoiceDesignSuggestion } from "./voiceDesignFormState";

describe("voiceDesign", () => {
  it("keeps the fixed age and quality ordering", () => {
    expect(voiceDesignAges).toEqual(["小学校低学年", "小学校高学年", "中学生", "高校生", "大学生", "20代", "30代", "40代", "50代", "60代", "初老", "長老"]);
    expect(voiceDesignGenders).toEqual(["男児", "女児", "男の子", "女の子", "男性", "女性", "中性"]);
    expect(voiceDesignQualities.flatMap((group) => group.values)).toHaveLength(18);
  });

  it("keeps legacy neutral-gender data compatible", () => {
    expect(normalizeVoiceDesign({ gender: "中性的" })).toMatchObject({ gender: "中性" });
  });

  it("builds only selected fields in the fixed inference order", () => {
    expect(voiceDesignKeywords({ age: "小学校低学年", gender: "男性", pitch: "やや高い", qualities: ["ハスキー", "太い", "胸に響く"], style: "威厳のある", notes: "語尾は短く。" })).toBe("小学校低学年の声。男性の声。やや高い声。ハスキーな声質。太い声質。胸に響く声質。威厳のある話し方。語尾は短く。");
  });

  it("starts empty and accepts contradictory qualities", () => {
    expect(hasVoiceDesignInput(emptyVoiceDesign())).toBe(false);
    expect(voiceDesignKeywords({ ...emptyVoiceDesign(), qualities: ["太い", "細い"] })).toBe("太い声質。細い声質。");
  });

  it("applies AI values only to empty fields and marks only applied fields", () => {
    const current = { ...emptyVoiceDesign(), age: "30代", qualities: ["太い"], notes: "既存の備考" };
    const proposal = { age: "20代", gender: "女性", pitch: "高い", qualities: ["細い"], style: "快活", notes: "AI備考" };
    const { next, applied } = mergeVoiceDesignSuggestion(current, proposal);
    expect(next).toEqual({ age: "30代", gender: "女性", pitch: "高い", qualities: ["太い"], style: "快活", notes: "既存の備考" });
    expect([...applied]).toEqual(["gender", "pitch", "style"]);
  });
});
