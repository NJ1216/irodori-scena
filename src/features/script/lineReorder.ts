import type { StudioProject } from "../../types";
import { sceneDialogueCues } from "./dialogueCues";

export type LineDropTarget = { sceneId: string; beforeLineId?: string };

export function visibleDragGhostCardCount(movingLineCount: number) {
  return Math.min(Math.max(movingLineCount, 1), 5);
}

export function movableLineIds(project: Pick<StudioProject, "scenes">, grabbedLineId: string, selectedLineIds: string[]) {
  const selected = selectedLineIds.includes(grabbedLineId) ? new Set(selectedLineIds) : new Set([grabbedLineId]);
  const result: string[] = [];
  for (const scene of project.scenes) {
    for (const cue of sceneDialogueCues(scene)) {
      if (cue.lines.some((line) => selected.has(line.id))) result.push(...cue.lines.map((line) => line.id));
    }
  }
  return result;
}

export function moveProjectLines(project: StudioProject, lineIds: string[], target: LineDropTarget): StudioProject {
  const moving = new Set(lineIds);
  if (!moving.size || (target.beforeLineId && moving.has(target.beforeLineId))) return project;
  const ordered = project.scenes.flatMap((scene) => scene.lines.filter((line) => moving.has(line.id)));
  if (!ordered.length) return project;
  const destination = project.scenes.find((scene) => scene.id === target.sceneId);
  if (!destination) return project;

  const scenes = project.scenes.map((scene) => ({ ...scene, lines: scene.lines.filter((line) => !moving.has(line.id)) }));
  const destinationAfterRemoval = scenes.find((scene) => scene.id === target.sceneId)!;
  const insertionIndex = target.beforeLineId ? destinationAfterRemoval.lines.findIndex((line) => line.id === target.beforeLineId) : destinationAfterRemoval.lines.length;
  if (insertionIndex < 0) return project;
  destinationAfterRemoval.lines.splice(insertionIndex, 0, ...ordered);

  const before = project.scenes.map((scene) => `${scene.id}:${scene.lines.map((line) => line.id).join(",")}`).join("|");
  const after = scenes.map((scene) => `${scene.id}:${scene.lines.map((line) => line.id).join(",")}`).join("|");
  return before === after ? project : { ...project, scenes };
}
