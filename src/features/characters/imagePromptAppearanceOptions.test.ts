import { describe, expect, it } from "vitest";
import { appearancePriority, prioritizedAppearanceOptions } from "./imagePromptAppearanceOptions";

describe("image prompt appearance options", () => {
  it("prioritizes female candidates only for explicit female values", () => {
    expect(appearancePriority("女性")).toBe("female");
    expect(appearancePriority(" female ")).toBe("female");
    expect(prioritizedAppearanceOptions("女").hairstyles[0]).toBe("ストレート");
    expect(prioritizedAppearanceOptions("女性").outfits[0]).toBe("カジュアル");
  });

  it("prioritizes male candidates only for explicit male values", () => {
    expect(appearancePriority("男性")).toBe("male");
    expect(appearancePriority("male")).toBe("male");
    expect(prioritizedAppearanceOptions("男").hairstyles[0]).toBe("マッシュ");
    expect(prioritizedAppearanceOptions("男性").outfits[1]).toBe("スーツ");
  });

  it("does not infer gender and always retains every candidate", () => {
    expect(appearancePriority("ノンバイナリー")).toBe("common");
    expect(appearancePriority("female character")).toBe("common");
    const options = prioritizedAppearanceOptions("");
    expect(options.hairstyles).toContain("ストレート");
    expect(options.hairstyles).toContain("カールヘア");
    expect(options.hairstyles).toContain("ヘアフラップ");
    expect(options.hairstyles).not.toContain("ロングストレート");
    expect(options.hairstyles).not.toContain("ベリーショート");
    expect(options.hairstyles).not.toContain("長髪");
    expect(options.outfits).toContain("詰襟制服");
    expect(options.outfits).toContain("セーラー服");
  });

  it("includes anime and manga hairstyle tags for every gender ordering", () => {
    const additions = [
      "アシンメトリー",
      "姫カット",
      "サイドカット",
      "ピクシーカット",
      "スパイクヘア",
      "モヒカン",
      "ローポニーテール",
      "ハイポニーテール",
      "サイドポニーテール",
      "ショートポニーテール",
      "低いツインテール",
      "ハーフアップツインテール",
      "片側三つ編み",
      "ツインブレイド",
      "ドリルヘア",
      "縦ロール",
      "髪を下ろす",
    ];
    for (const gender of ["女性", "男性", ""]) {
      expect(prioritizedAppearanceOptions(gender).hairstyles).toEqual(expect.arrayContaining(additions));
    }
  });
});
