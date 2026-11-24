import { describe, expect, it } from "vitest";

import type { CharacterProfile, StudioProject } from "../../types";
import { compactCharacterSettingWidthClass, formatDuration, formatProjectPlaybackDuration, lineTakeFileName, applyCharacterProfileSuggestion, displayNameAfterProfileSuggestion, paginateNotebookDetails, projectPlaybackDurationSeconds, qualityLabel, sceneLabel } from "./studio-utils";

describe("studio presentation utilities", () => {
  it("keeps quality labels and duration formatting stable", () => {
    expect(qualityLabel).toEqual({
      turbo: "高速 · Sway 8",
      fast: "バランス · Sway 16",
      quality: "高品質 · Linear 40",
    });
    expect(formatDuration(59.6)).toBe("1分0秒");
    expect(formatDuration(61)).toBe("1分1秒");
    expect(formatDuration(3723)).toBe("1時間2分3秒");
  });

  it("keeps scene labels stable beyond the first alphabet", () => {
    expect([0, 25, 26, 51, 52].map(sceneLabel)).toEqual(["A", "Z", "Aa", "Az", "Ba"]);
  });

  it("uses the project-wide line number width for individual WAV names", () => {
    expect(lineTakeFileName(1, "こんにちは。")).toBe("001_こんにちは。.wav");
    expect(lineTakeFileName(1000, "🐢質問/回答?!")).toBe("1000_質問_回答_.wav");
  });
});

describe("project timing and cast presentation", () => {
  it("sums selected take durations and only the intervening gaps", () => {
    const project = {
      scenes: [
        {
          lines: [
            {
              characterId: "cast",
              text: "最初の発話",
              gapSeconds: 1.2,
              selectedTakeId: "take-1",
              takes: [
                { id: "take-1", durationSeconds: 3.4 },
                { id: "old", durationSeconds: 99 },
              ],
            },
            {
              characterId: "cast",
              text: "二つ目の発話",
              selectedTakeId: "take-2",
              takes: [{ id: "take-2", durationSeconds: 5.6 }],
            },
          ],
        },
        {
          lines: [
            {
              characterId: "cast",
              text: "最後の発話",
              gapSeconds: 123,
              selectedTakeId: "take-3",
              takes: [{ id: "take-3", durationSeconds: 7.8 }],
            },
            { characterId: "cast", text: "   ", selectedTakeId: null, takes: [] },
          ],
        },
      ],
      settings: { lineGap: 0.7 },
    } as unknown as StudioProject;
    expect(projectPlaybackDurationSeconds(project)).toBeCloseTo(18.7);
  });
  it("waits for every spoken line to have a selected take with a valid duration", () => {
    const project = {
      scenes: [
        {
          lines: [
            { characterId: "cast", text: "音声あり", selectedTakeId: "take-1", takes: [{ id: "take-1", durationSeconds: 1 }] },
            { characterId: "cast", text: "未選択", selectedTakeId: null, takes: [{ id: "take-2", durationSeconds: 2 }] },
          ],
        },
      ],
      settings: {},
    } as unknown as StudioProject;

    expect(projectPlaybackDurationSeconds(project)).toBeUndefined();
    project.scenes[0].lines[1].selectedTakeId = "take-2";
    project.scenes[0].lines[1].takes[0].durationSeconds = Number.NaN;
    expect(projectPlaybackDurationSeconds(project)).toBeUndefined();
  });

  it("formats project durations with minutes and seconds, adding hours when needed", () => {
    expect(formatProjectPlaybackDuration(0)).toBe("0分0秒");
    expect(formatProjectPlaybackDuration(61)).toBe("1分1秒");
    expect(formatProjectPlaybackDuration(3_661)).toBe("1時間1分1秒");
  });

  it("applies only fields present in an accepted partial suggestion", () => {
    const current: CharacterProfile = {
      personality: "既存の性格",
      castRelations: { castA: { address: "先輩", relationship: "既存の関係" } },
    };
    const suggestion: CharacterProfile = {
      personality: "上書きしてはいけない性格",
      hobbies: "読書",
      castRelations: {
        castA: { address: "上書き不可", relationship: "上書きしてはいけない関係" },
        castB: { address: "Bちゃん", relationship: "新しい関係" },
      },
    };

    expect(applyCharacterProfileSuggestion(current, suggestion)).toEqual({
      personality: "上書きしてはいけない性格",
      hobbies: "読書",
      castRelations: {
        castA: { address: "上書き不可", relationship: "上書きしてはいけない関係" },
        castB: { address: "Bちゃん", relationship: "新しい関係" },
      },
    });
  });

  it("uses the first generated nonblank alias only when the display name is blank", () => {
    const profile = { aliases: [" ", "リリ", "りっちゃん"] };
    expect(displayNameAfterProfileSuggestion("", profile)).toBe("リリ");
    expect(displayNameAfterProfileSuggestion("既存名", profile)).toBe("既存名");
    expect(displayNameAfterProfileSuggestion("", {})).toBe("");
  });

  it("paginates notebook details without dropping text", () => {
    const value = "あ".repeat(900);
    const pages = paginateNotebookDetails([["背景", value]]);
    expect(
      pages
        .flat()
        .map(([, text]) => text)
        .join(""),
    ).toBe(value);
    expect(pages.length).toBeGreaterThan(1);
    expect(compactCharacterSettingWidthClass("あ".repeat(22))).toBe("is-extra-wide");
  });
});

describe("selected-take overlap duration", () => {
  it("clamps a negative gap to the shorter following selected take", () => {
    const project = {
      scenes: [
        {
          lines: [
            { characterId: "cast", text: "長い先発", gapSeconds: -5, selectedTakeId: "a", takes: [{ id: "a", durationSeconds: 3 }] },
            { characterId: "cast", text: "短い後発", selectedTakeId: "b", takes: [{ id: "b", durationSeconds: 0.5 }] },
          ],
        },
      ],
      settings: { lineGap: 0.7 },
    } as unknown as StudioProject;
    expect(projectPlaybackDurationSeconds(project)).toBe(3);
  });
});
