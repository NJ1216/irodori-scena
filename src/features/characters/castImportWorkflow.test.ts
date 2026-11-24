import { describe, expect, it } from "vitest";
import type { CastImportPreparation } from "../../types";
import { actionableCastImportConflicts, castImportResultMessage, commitUncontestedCastImport, skippedCastImportReasons } from "./castImportWorkflow";

const cast = { id: "cast", name: "彩", profile: "", voiceKeywords: "", referenceAudioUrl: "/voice.wav", referenceFile: "/voice.wav", createdAt: 1 };

describe("cast import workflow", () => {
  it("reports only conflicts that require a duplicate decision", () => {
    const preparation = {
      sessionId: "session",
      expiresInSeconds: 60,
      errors: [],
      items: [
        { key: "new", path: "new.scenacast", status: "new", incoming: cast, existing: null },
        { key: "same", path: "same.scenacast", status: "identical", incoming: cast, existing: cast },
        { key: "conflict", path: "duplicate.scenacast", status: "conflict", incoming: cast, existing: cast },
      ],
    } satisfies CastImportPreparation;
    expect(actionableCastImportConflicts(preparation).map((item) => item.path)).toEqual(["duplicate.scenacast"]);
  });

  it("does not double-count identical files already returned as skipped", () => {
    expect(castImportResultMessage(2, 1, 0)).toBe("2件を取り込み、1件をスキップしました。");
  });

  it("commits immediately when no duplicate needs a decision", async () => {
    const commit = async (sessionId: string) => `committed:${sessionId}`;
    const preparation = { sessionId: "session", expiresInSeconds: 60, errors: [], items: [{ key: "new", path: "new.scenacast", status: "new", incoming: cast, existing: null }] } satisfies CastImportPreparation;
    await expect(commitUncontestedCastImport(preparation, commit)).resolves.toBe("committed:session");
  });

  it("explains automatic and chosen skips without listing imported files", () => {
    const preparation = {
      sessionId: "session",
      expiresInSeconds: 60,
      errors: [],
      items: [
        { key: "new", path: "new.scenacast", status: "new", incoming: cast, existing: null },
        { key: "same", path: "same.scenacast", status: "identical", incoming: cast, existing: cast },
        { key: "conflict", path: "duplicate.scenacast", status: "conflict", incoming: cast, existing: cast },
      ],
    } satisfies CastImportPreparation;
    expect(
      skippedCastImportReasons(preparation, [
        { key: "same", status: "identical" },
        { key: "conflict", status: "conflict" },
      ]),
    ).toEqual([
      { path: "same.scenacast", reason: "登録済みのキャストと同じ内容です" },
      { path: "duplicate.scenacast", reason: "スキップが選択されました" },
    ]);
  });
});
