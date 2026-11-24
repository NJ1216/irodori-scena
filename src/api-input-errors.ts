const aiFields: Record<string, string> = {
  theme: "テーマ／状況",
  character_ids: "参加キャスト",
  target_minutes: "だいたいの総尺",
  speech_rate: "話速",
  line_gap: "発話間隔",
  cast_settings: "キャスト設定",
  allowed_emojis: "表情付けに利用する絵文字",
  performance_speech_rate_min: "話速の最小値",
  performance_speech_rate_max: "話速の最大値",
  performance_gap_min: "間の最小値",
  performance_gap_max: "間の最大値",
  line_ids: "対象の発話行",
};

const constraints: Record<string, string> = {
  "performance_speech_rate_min must not exceed performance_speech_rate_max": "話速の最小値は最大値以下にしてください。",
  "performance_gap_min must not exceed performance_gap_max": "間の最小値は最大値以下にしてください。",
  "draft speech_rate must be numeric": "話速の設定を確認してください。",
};

// Translate known input failures, never expose raw input, JSON or server internals.
export function aiJobInputFailure(detail: unknown): string | null {
  if (detail === "既定のLLMモデルを接続ページで選択してください。") return "設定ページで既定のLLMモデルを選択してください。";
  if (!Array.isArray(detail)) return null;
  const messages = detail
    .map((issue: unknown) => {
      if (!issue || typeof issue !== "object") return "";
      const { loc, msg, type } = issue as { loc?: unknown; msg?: unknown; type?: unknown };
      const field = Array.isArray(loc) ? loc.find((part) => typeof part === "string" && Object.hasOwn(aiFields, part)) : undefined;
      if (field === "theme") return type === "string_too_long" ? "テーマ／状況は4000文字以内で入力してください。" : "テーマ／状況を入力してください。短い言葉でも構いません。";
      if (field) return `「${aiFields[field]}」の入力内容を確認してください。`;
      const reason = typeof msg === "string" ? msg.replace(/^Value error, /, "") : "";
      if (Object.hasOwn(constraints, reason)) return constraints[reason];
      if (reason.startsWith("allowed_emojis contains unsupported emoji:")) return "表情付けに利用する絵文字を選び直してください。";
      return "";
    })
    .filter(Boolean);
  return messages.length ? [...new Set(messages)].join(" ") : null;
}
