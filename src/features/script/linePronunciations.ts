import type { LinePronunciation } from "../../types";

export const codePoints = (text: string) => Array.from(text);

export function normalizeLinePronunciations(text: string, values: LinePronunciation[] = []) {
  const points = codePoints(text);
  const accepted: LinePronunciation[] = [];
  for (const item of [...values].sort((a, b) => a.start - b.start || a.end - b.end)) {
    if (!item.id || !item.reading || item.reading.includes("\n") || item.start < 0 || item.end <= item.start || item.end > points.length) continue;
    if (points.slice(item.start, item.end).join("") !== item.text) continue;
    if (accepted.some((other) => item.start < other.end && other.start < item.end)) continue;
    accepted.push({ ...item });
  }
  return accepted;
}

export function updatePronunciationsForText(oldText: string, newText: string, values: LinePronunciation[] = []) {
  const before = codePoints(oldText);
  const after = codePoints(newText);
  let prefix = 0;
  while (prefix < before.length && prefix < after.length && before[prefix] === after[prefix]) prefix += 1;
  let suffix = 0;
  while (suffix < before.length - prefix && suffix < after.length - prefix && before[before.length - 1 - suffix] === after[after.length - 1 - suffix]) suffix += 1;
  const oldEnd = before.length - suffix;
  const newEnd = after.length - suffix;
  const delta = newEnd - oldEnd;
  return normalizeLinePronunciations(
    newText,
    values.flatMap((item) => {
      if (oldEnd <= item.start) return [{ ...item, start: item.start + delta, end: item.end + delta }];
      if (prefix >= item.end) return [item];
      return [];
    }),
  );
}

export function selectionConflict(text: string, start: number, end: number, values: LinePronunciation[] = [], editingId?: string) {
  if (start === end) return "読みを設定する文字を選択してください。";
  if (codePoints(text).slice(start, end).includes("\n")) return "改行をまたぐ範囲には読みを設定できません。";
  if (values.some((item) => item.id !== editingId && start < item.end && item.start < end)) return "設定済みの読みと重なる範囲は選択できません。";
  return null;
}
