export type ProjectMenuAction = "new" | "save" | "optimize" | "open" | "script-import" | "ai-direction" | "export" | "cast-export" | "project-backup" | "clear-takes" | "lora-training";

export const projectMenuActionLabel: Record<ProjectMenuAction, string> = {
  new: "新規作成",
  save: "保存",
  optimize: "最適化保存",
  open: "開く",
  "script-import": "台本読み込み",
  "ai-direction": "AI演出",
  export: "エクスポート",
  "cast-export": "キャストエクスポート",
  "project-backup": "プロジェクトのバックアップ",
  "lora-training": "LoRA管理",
  "clear-takes": "生成テイク初期化",
};
