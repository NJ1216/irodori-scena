export type FileDropClassification = { kind: "project"; path: string; unsupported: number } | { kind: "casts"; paths: string[]; unsupported: number } | { kind: "invalid"; reason: string; unsupported: number };

export function classifyDroppedPaths(paths: string[]): FileDropClassification {
  const projects = paths.filter((path) => path.toLowerCase().endsWith(".scena"));
  const casts = paths.filter((path) => path.toLowerCase().endsWith(".scenacast"));
  const unsupported = paths.length - projects.length - casts.length;
  if (projects.length === 1 && casts.length === 0) return { kind: "project", path: projects[0], unsupported };
  if (projects.length === 0 && casts.length > 0) return { kind: "casts", paths: casts, unsupported };
  if (projects.length > 1) return { kind: "invalid", reason: "プロジェクトは1件ずつドロップしてください。", unsupported };
  if (projects.length && casts.length) return { kind: "invalid", reason: "プロジェクトとキャストは分けてドロップしてください。", unsupported };
  return { kind: "invalid", reason: "対応する .scena または .scenacast ファイルがありません。", unsupported };
}

export function fileDropMessage(value: FileDropClassification) {
  if (value.kind === "project") return "プロジェクトを開く";
  if (value.kind === "casts") return `${value.paths.length}件のキャストを読み込む`;
  return value.reason;
}
