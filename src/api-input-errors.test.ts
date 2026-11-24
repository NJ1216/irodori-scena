import { afterEach, expect, it, vi } from "vitest";
import { api } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it.each([
  [[{ loc: ["body", "theme"], type: "string_too_short", input: "" }], "テーマ／状況を入力してください。短い言葉でも構いません。"],
  [[{ loc: ["body", "theme"], type: "string_too_long" }], "テーマ／状況は4000文字以内で入力してください。"],
  [[{ loc: ["body"], type: "value_error", msg: "Value error, performance_gap_min must not exceed performance_gap_max" }], "間の最小値は最大値以下にしてください。"],
  ["既定のLLMモデルを接続ページで選択してください。", "設定ページで既定のLLMモデルを選択してください。"],
  [[{ loc: ["body", "unknown_internal"], msg: "private detail" }], "入力内容を確認して、もう一度お試しください。"],
])("shows actionable AI input errors without exposing raw details", async (detail, expected) => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail }) }));
  await expect(api.startAiJob({ mode: "draft" })).rejects.toThrow(expected);
});
