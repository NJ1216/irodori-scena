import type { LinePronunciation, StudioProject } from "../../types";
import { codePoints } from "./linePronunciations";

export type ScriptMatch = { lineId: string; start: number; end: number };

export function findScriptMatches(project: Pick<StudioProject, "scenes">, query: string): ScriptMatch[] {
  if (!query) return [];
  const needle = query.toLocaleLowerCase();
  return project.scenes.flatMap((scene) =>
    scene.lines.flatMap((line) => {
      const text = line.text.toLocaleLowerCase();
      const matches: ScriptMatch[] = [];
      for (let start = 0; start <= text.length - needle.length;) {
        const found = text.indexOf(needle, start);
        if (found < 0) break;
        matches.push({ lineId: line.id, start: found, end: found + needle.length });
        start = found + Math.max(1, needle.length);
      }
      return matches;
    }),
  );
}

function utf16ToPoint(text: string, offset: number) {
  return codePoints(text.slice(0, offset)).length;
}

export function replaceLineMatches(text: string, pronunciations: LinePronunciation[] | undefined, matches: Array<Pick<ScriptMatch, "start" | "end">>, replacement: string) {
  const ordered = [...matches].sort((left, right) => right.start - left.start);
  let next = text;
  let values = [...(pronunciations ?? [])];
  for (const match of ordered) {
    const start = utf16ToPoint(text, match.start);
    const end = utf16ToPoint(text, match.end);
    const delta = codePoints(replacement).length - (end - start);
    values = values.flatMap((item) => {
      if (item.end <= start) return [item];
      if (item.start >= end) return [{ ...item, start: item.start + delta, end: item.end + delta }];
      return [];
    });
    next = next.slice(0, match.start) + replacement + next.slice(match.end);
  }
  return { text: next, pronunciations: values };
}
