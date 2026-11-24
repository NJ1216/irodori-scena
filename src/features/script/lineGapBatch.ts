import type { StudioProject } from "../../types";
import { allProjectCues } from "./dialogueCues";

export function adjustedLineGap(value: number | undefined, defaultGap: number, delta: number) {
  return Math.round(Math.max(-9999, Math.min(9999, (value ?? defaultGap) + delta)) * 10) / 10;
}

export function adjustSelectedLineGaps(project: StudioProject, selectedLineIds: string[], directions: readonly (-1 | 1)[]): StudioProject {
  const selected = new Set(selectedLineIds);
  const cues = allProjectCues(project);
  const targetIds = new Set(
    cues
      .slice(0, -1)
      .filter(({ cue }) => cue.lines.some((line) => selected.has(line.id)))
      .map(({ cue }) => cue.lines[0].id),
  );
  if (!targetIds.size) return project;
  const defaultGap = project.settings.lineGap ?? 0.7;
  return {
    ...project,
    scenes: project.scenes.map((scene) => ({
      ...scene,
      lines: scene.lines.map((line) => (targetIds.has(line.id) ? { ...line, gapSeconds: directions.reduce<number | undefined>((value, direction) => adjustedLineGap(value, defaultGap, direction * 0.1), line.gapSeconds) } : line)),
    })),
  };
}

export function setSelectedLineGaps(project: StudioProject, selectedLineIds: string[], value: number | undefined): StudioProject {
  const selected = new Set(selectedLineIds);
  const targetIds = new Set(
    allProjectCues(project)
      .slice(0, -1)
      .filter(({ cue }) => cue.lines.some((line) => selected.has(line.id)))
      .map(({ cue }) => cue.lines[0].id),
  );
  if (!targetIds.size) return project;
  return {
    ...project,
    scenes: project.scenes.map((scene) => ({
      ...scene,
      lines: scene.lines.map((line) => (targetIds.has(line.id) ? { ...line, gapSeconds: value } : line)),
    })),
  };
}
