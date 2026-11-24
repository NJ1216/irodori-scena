import type { LoraInputRow } from "../../types/lora";
export function inputLabel(row: LoraInputRow) {
  return row.relativePath ?? row.wavName ?? row.textName ?? "音声がありません";
}
export function inputIssues(row: LoraInputRow) {
  if (row.blocked) return row.issues;
  return row.issues.filter((issue) => !row.text.trim() || !/text|txt|本文/i.test(issue));
}
export function inputStatus(row: LoraInputRow, excluded: boolean) {
  if (excluded) return "除外";
  if (row.blocked) return "対応を確認";
  if (!row.wavName) return "音声なし";
  if (!row.text.trim()) return "台詞なし";
  if (inputIssues(row).length) return "要確認";
  return row.textName ? "対応済み" : "手入力済み";
}
export function inputNeedsReview(row: LoraInputRow) {
  return !!row.blocked || !row.wavName || !row.text.trim() || inputIssues(row).length > 0;
}
