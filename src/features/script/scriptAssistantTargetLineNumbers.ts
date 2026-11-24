import type { AssistantTargetLine } from "./ScriptAssistantTargetLines";

export function targetLineNumberRanges(lines: AssistantTargetLine[]) {
  const numbers = Array.from(new Set(lines.map(({ lineNumber }) => lineNumber).filter((value): value is number => value !== null)));
  const ranges: Array<[number, number]> = [];
  for (const number of numbers) {
    const last = ranges.at(-1);
    if (last && number === last[1] + 1) last[1] = number;
    else ranges.push([number, number]);
  }
  return ranges;
}

export function formatTargetLineNumbers(lines: AssistantTargetLine[]) {
  return (
    targetLineNumberRanges(lines)
      .map(([start, end]) => (start === end ? String(start) : `${start}〜${end}`))
      .join("、") || "—"
  );
}
