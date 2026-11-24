import { describe, expect, it } from "vitest";
import type { Character } from "../../types";
import { matchedCharacterId, parseScriptImport } from "./scriptImport";

const riri = {
  id: "riri",
  name: "Riri",
  profile: "",
  voiceKeywords: "",
  referenceAudioUrl: "",
  referenceFile: "",
  createdAt: 1,
} satisfies Character;
const tachibana = {
  id: "tachibana",
  name: "橘 美咲",
  profile: "",
  voiceKeywords: "",
  referenceAudioUrl: "",
  referenceFile: "",
  createdAt: 1,
} satisfies Character;

describe("script import", () => {
  it("recognizes quoted and common delimiter speaker notation while inheriting the previous speaker", () => {
    expect(parseScriptImport("Riri「こんにちは。」\n橘:やあ。\nB|本文:補足\n台詞だけ")).toEqual([
      { speaker: "Riri", text: "こんにちは。" },
      { speaker: "橘", text: "やあ。" },
      { speaker: "B", text: "本文:補足" },
      { speaker: "B", text: "台詞だけ" },
    ]);
  });

  it("prioritizes delimiters and preserves quotation marks in dialogue text", () => {
    expect(parseScriptImport("Ａ：そん時に『誰が誰を好きか』…\nＢ：「聞いたよ」")).toEqual([
      { speaker: "Ａ", text: "そん時に『誰が誰を好きか』…" },
      { speaker: "Ｂ", text: "「聞いたよ」" },
    ]);
  });

  it("keeps quoted speech inside an indented continuation with the previous cast", () => {
    expect(parseScriptImport("Ａ：オブラートに包もうとして劇的な表現をしたね。\n　　なにエキサイティングな顔って。どういうこと？\nＢ：頑張ってみる。\nＡ：よし、じゃあはい、イメージしてー。イメージしてー。\n　　いくよー。……『始めまして。彼女です』\nＢ：どうだった？")).toEqual([
      { speaker: "Ａ", text: "オブラートに包もうとして劇的な表現をしたね。" },
      { speaker: "Ａ", text: "なにエキサイティングな顔って。どういうこと？" },
      { speaker: "Ｂ", text: "頑張ってみる。" },
      { speaker: "Ａ", text: "よし、じゃあはい、イメージしてー。イメージしてー。" },
      { speaker: "Ａ", text: "いくよー。……『始めまして。彼女です』" },
      { speaker: "Ｂ", text: "どうだった？" },
    ]);
  });

  it("inherits the previous cast when another quoted phrase precedes the final quote", () => {
    expect(parseScriptImport("Ａ：冒頭。\n　　「前置き」『引用』")).toEqual([
      { speaker: "Ａ", text: "冒頭。" },
      { speaker: "Ａ", text: "「前置き」『引用』" },
    ]);
  });

  it("removes only the outer matching quotation pair from speaker notation", () => {
    expect(parseScriptImport("A「xx「xx」xx」\nA「xx『xx』xx」\nA『xx「xx」xx』\nA「xx:xx」")).toEqual([
      { speaker: "A", text: "xx「xx」xx" },
      { speaker: "A", text: "xx『xx』xx" },
      { speaker: "A", text: "xx「xx」xx" },
      { speaker: "A", text: "xx:xx" },
    ]);
  });

  it("keeps inherited dialogue as separate lines across blanks and indentation", () => {
    expect(parseScriptImport("Ａ：座れよ。\n\n　　――まあ座れよ。\nＢ「手紙を読む」\n  親愛なるあなたへ。")).toEqual([
      { speaker: "Ａ", text: "座れよ。" },
      { speaker: "Ａ", text: "――まあ座れよ。" },
      { speaker: "Ｂ", text: "手紙を読む" },
      { speaker: "Ｂ", text: "親愛なるあなたへ。" },
    ]);
  });

  it("leaves leading unassigned lines unassigned and preserves all-unassigned imports", () => {
    expect(parseScriptImport("前置き\nA:本文\n続き")).toEqual([
      { speaker: null, text: "前置き" },
      { speaker: "A", text: "本文" },
      { speaker: "A", text: "続き" },
    ]);
    expect(parseScriptImport("一行目\n\n　二行目")).toEqual([
      { speaker: null, text: "一行目" },
      { speaker: null, text: "二行目" },
    ]);
  });

  it("matches a unique cast by full name or surname", () => {
    expect(matchedCharacterId("Riri", [riri, tachibana])).toBe("riri");
    expect(matchedCharacterId("橘", [riri, tachibana])).toBe("tachibana");
    expect(matchedCharacterId("田村", [riri, tachibana])).toBe("");
  });
});
