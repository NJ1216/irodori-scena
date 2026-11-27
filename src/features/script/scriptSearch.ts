import type { LinePronunciation, StudioProject } from "../../types";
import { codePoints } from "./linePronunciations";

export type ScriptMatch = { lineId: string; start: number; end: number };

export function findScriptMatches(project: Pick<StudioProject, "scenes">, query: string): ScriptMatch[] {
  if (!query) return [];
  // Match on the original text so offsets stay valid for replaceLineMatches; lowercasing
  // the text first can change its length (for example "İ").
  const pattern = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "giu");
  return project.scenes.flatMap((scene) => scene.lines.flatMap((line) => Array.from(line.text.matchAll(pattern), (found) => ({ lineId: line.id, start: found.index, end: found.index + found[0].length }))));
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
