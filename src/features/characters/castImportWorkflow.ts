import type { CastImportPreparation } from "../../types";

export function castImportResultMessage(applied: number, skipped: number, invalid: number, warnings: string[] = []) {
  const base = `${applied}件を取り込み、${skipped}件をスキップしました。`;
  return [invalid ? `${base} ${invalid}件は破損または非対応でした。` : base, ...warnings].join(" ");
}

export function actionableCastImportConflicts(preparation: CastImportPreparation) {
  return preparation.items.filter((item) => item.status === "conflict");
}

export async function commitUncontestedCastImport<T>(preparation: CastImportPreparation, commit: (sessionId: string) => Promise<T>) {
  if (actionableCastImportConflicts(preparation).length) return null;
  return commit(preparation.sessionId);
}

export function skippedCastImportReasons(preparation: CastImportPreparation, skipped: Array<{ key: string; status: string }>) {
  const byKey = new Map(preparation.items.map((item) => [item.key, item]));
  return skipped.flatMap((result) => {
    const item = byKey.get(result.key);
    if (!item) return [];
    return [{ path: item.path, reason: result.status === "identical" ? "登録済みのキャストと同じ内容です" : "スキップが選択されました" }];
  });
}
