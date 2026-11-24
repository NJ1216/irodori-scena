import type { StudioProject } from "../../types";

export function rewriteFocusAfterApply(project: StudioProject, next: StudioProject, targetIds: string[], focusedLineId: string | null) {
  const previousIds = project.scenes.flatMap((scene) => scene.lines.map((line) => line.id));
  const targetIndexes = targetIds.map((id) => previousIds.indexOf(id)).filter((index) => index >= 0);
  const firstTargetIndex = targetIndexes.length ? Math.min(...targetIndexes) : 0;
  const nextIds = next.scenes.flatMap((scene) => scene.lines.map((line) => line.id));
  if (focusedLineId && nextIds.includes(focusedLineId)) return focusedLineId;
  return nextIds[Math.min(firstTargetIndex, Math.max(0, nextIds.length - 1))] ?? null;
}
