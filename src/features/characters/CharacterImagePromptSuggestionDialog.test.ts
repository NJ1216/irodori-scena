import { describe, expect, it } from "vitest";
import { EXPRESSION_GROUPS } from "./imagePromptExpressions";
import { ACCESSORY_GROUPS, ACCESSORY_OPTIONS } from "./imagePromptAppearanceOptions";
import { OCCUPATION_GROUPS } from "./imagePromptOccupations";
import {
  AGE_IMPRESSION_OPTIONS,
  BACKGROUND_OPTIONS,
  CAMERA_ANGLE_DESCRIPTIONS,
  CAMERA_ANGLE_GROUPS,
  CAMERA_ANGLE_OPTIONS,
  COMPOSITION_DESCRIPTIONS,
  COMPOSITION_GROUPS,
  COMPOSITION_OPTIONS,
  FRECKLES_MOLES_OPTIONS,
  GESTURE_OPTIONS,
  HEIGHT_OPTIONS,
  POSE_OPTIONS,
  SCARS_OPTIONS,
  SCREEN_EFFECT_DESCRIPTIONS,
  SCREEN_EFFECT_GROUPS,
  SCREEN_EFFECT_OPTIONS,
  TATTOOS_OPTIONS,
} from "./imagePromptOptionCatalog";

describe("image prompt expression groups", () => {
  it("offers fifteen distinct specific expressions in every category", () => {
    expect(EXPRESSION_GROUPS).toHaveLength(5);
    expect(EXPRESSION_GROUPS.every((group) => group.options.length === 15)).toBe(true);
    const options = EXPRESSION_GROUPS.flatMap((group) => group.options);
    expect(new Set(options).size).toBe(75);
    expect(options).not.toEqual(expect.arrayContaining(["真顔", "嬉しい", "笑い", "悲しい", "怒り"]));
  });

  it("orders age and height presets and expands facial features", () => {
    expect(HEIGHT_OPTIONS).toEqual(["100cm", "105cm", "110cm", "115cm", "120cm", "125cm", "130cm", "135cm", "140cm", "145cm", "150cm", "155cm", "160cm", "165cm", "170cm", "175cm", "180cm", "185cm", "190cm", "195cm", "200cm"]);
    expect(AGE_IMPRESSION_OPTIONS).toEqual(["0才", "1~2才", "3~5才", "6~8才", "9~11才", "12~14才", "15~17才", "18~22才", "23~29才", "30~39才", "40~49才", "50~59才", "60~69才", "70~79才", "80才以上"]);
    expect(FRECKLES_MOLES_OPTIONS).toHaveLength(13);
    expect(SCARS_OPTIONS).toHaveLength(14);
    expect(TATTOOS_OPTIONS).toHaveLength(14);
  });
});

describe("image prompt fixed option catalog", () => {
  it("contains the complete pose, gesture, framing, angle, and background choices", () => {
    expect(POSE_OPTIONS).toHaveLength(10);
    expect(GESTURE_OPTIONS).toHaveLength(12);
    expect(COMPOSITION_OPTIONS).toEqual([
      "顔を大きく写す",
      "顔と胸元を中心に写す",
      "上半身を写す",
      "下半身を写す",
      "膝上まで写す",
      "全身を写す",
      "足を画面外にする",
      "横顔を写す",
      "広い範囲を写す",
      "遠近感を強調する",
      "遠景を霞ませる",
      "魚眼レンズで写す",
      "横長のパノラマにする",
      "消失点を強調する",
      "余白を活かす",
      "一部を水中に入れる",
      "アイソメトリックで描く",
      "立ち絵として描く",
      "背景に拡大像を重ねる",
      "背景に人物像を投影する",
    ]);
    expect(COMPOSITION_GROUPS.flatMap((group) => group.options).sort()).toEqual([...COMPOSITION_OPTIONS].sort());
    expect(Object.keys(COMPOSITION_DESCRIPTIONS)).toEqual(COMPOSITION_OPTIONS);
    expect(Object.values(COMPOSITION_DESCRIPTIONS).every((description) => description.length >= 20)).toBe(true);
    expect(COMPOSITION_OPTIONS).not.toEqual(expect.arrayContaining(["複数視点", "横一列に並べる", "列に並べる", "対称構図"]));
    expect(CAMERA_ANGLE_OPTIONS).toEqual(["正面から撮る", "真横から撮る", "後ろから撮る", "斜めに傾けて撮る", "ドラマチックな斜め構図", "真上から見下ろす", "空中から広く見下ろす", "鳥の目線から見下ろす", "上から見下ろす", "目線の高さから撮る", "下から見上げる", "一人称視点で撮る"]);
    expect(CAMERA_ANGLE_GROUPS.flatMap((group) => group.options).sort()).toEqual([...CAMERA_ANGLE_OPTIONS].sort());
    expect(Object.keys(CAMERA_ANGLE_DESCRIPTIONS)).toEqual(CAMERA_ANGLE_OPTIONS);
    expect(Object.values(CAMERA_ANGLE_DESCRIPTIONS).every((description) => description.length >= 20)).toBe(true);
    expect(SCREEN_EFFECT_OPTIONS).toHaveLength(19);
    expect(SCREEN_EFFECT_GROUPS.flatMap((group) => group.options).sort()).toEqual([...SCREEN_EFFECT_OPTIONS].sort());
    expect(Object.keys(SCREEN_EFFECT_DESCRIPTIONS)).toEqual(SCREEN_EFFECT_OPTIONS);
    expect(Object.values(SCREEN_EFFECT_DESCRIPTIONS).every((description) => description.length >= 20)).toBe(true);
    expect(SCREEN_EFFECT_OPTIONS).toEqual(expect.arrayContaining(["光をにじませる", "被写界深度をつける", "動きをぼかす", "グリッチノイズを入れる", "周辺を暗くする"]));
    expect(BACKGROUND_OPTIONS).toHaveLength(18);
    expect(BACKGROUND_OPTIONS[0]).toBe("白背景（背景なし）");
  });

  it("groups broad occupation and accessory catalogs without duplicate choices", () => {
    const occupations = OCCUPATION_GROUPS.flatMap((group) => group.options);
    expect(occupations.length).toBeGreaterThan(100);
    expect(occupations).toEqual(expect.arrayContaining(["赤ちゃん", "中学生", "警察官", "看護師", "陸上選手", "宇宙飛行士", "魔法使い"]));
    expect(new Set(occupations).size).toBe(occupations.length);
    expect(ACCESSORY_GROUPS.length).toBeGreaterThanOrEqual(6);
    expect(ACCESSORY_OPTIONS).toEqual(expect.arrayContaining(["ティアラ", "王冠", "花冠", "モノクル", "勲章", "杖"]));
    expect(new Set(ACCESSORY_OPTIONS).size).toBe(ACCESSORY_OPTIONS.length);
  });
});
