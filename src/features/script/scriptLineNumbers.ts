import type { StudioProject } from "../../types";
import { sceneDialogueCues } from "./dialogueCues";

export type NumberedLine = {
  sceneId: string;
  lineId: string;
  number: number | null;
  referenceNumber: number;
};

export function numberedScriptLines(project: Pick<StudioProject, "scenes">): NumberedLine[] {
  let number = 0;
  return project.scenes.flatMap((scene) =>
    sceneDialogueCues(scene).flatMap((cue) => {
      const head = cue.lines[0];
      const enabled = head.enabled !== false;
      const cueNumber = enabled ? ++number : null;
      const referenceNumber = enabled ? number : number + 1;
      return cue.lines.map((line) => ({ sceneId: scene.id, lineId: line.id, number: cueNumber, referenceNumber }));
    }),
  );
}

export function scriptLineNumberMap(project: Pick<StudioProject, "scenes">) {
  return new Map(numberedScriptLines(project).map((item) => [item.lineId, item.number]));
}

export function scriptLineMaps(project: Pick<StudioProject, "scenes">) {
  const numbers = new Map<string, number | null>();
  const references = new Map<string, number>();
  for (const item of numberedScriptLines(project)) {
    numbers.set(item.lineId, item.number);
    references.set(item.lineId, item.referenceNumber);
  }
  return { numbers, references };
}

export function minimumLineNumberWidth(project: Pick<StudioProject, "scenes">) {
  const count = new Set(
    numberedScriptLines(project)
      .filter((item) => item.number !== null)
      .map((item) => item.number),
  ).size;
  return Math.max(3, String(Math.max(1, count)).length);
}
