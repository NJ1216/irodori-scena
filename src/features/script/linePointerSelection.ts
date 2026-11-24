import type { StudioProject } from "../../types";

export type LineSelectionModifiers = { shiftKey: boolean; altKey: boolean; preserveSelection?: boolean };

export type LinePointerSelection = {
  focusedLineId: string | null;
  selectedLineIds: string[];
  anchorLineId: string | null;
};

function rangeSelection(lineIds: string[], clickedLineId: string, focusedLineId: string | null, selectedLineIds: string[], anchorLineId: string | null): LinePointerSelection {
  const clickedIndex = lineIds.indexOf(clickedLineId);
  const fallbackAnchor = focusedLineId && lineIds.includes(focusedLineId) ? focusedLineId : (selectedLineIds.find((lineId) => lineIds.includes(lineId)) ?? clickedLineId);
  const nextAnchor = anchorLineId && lineIds.includes(anchorLineId) ? anchorLineId : fallbackAnchor;
  const anchorIndex = lineIds.indexOf(nextAnchor);
  return {
    focusedLineId: clickedLineId,
    selectedLineIds: lineIds.slice(Math.min(anchorIndex, clickedIndex), Math.max(anchorIndex, clickedIndex) + 1),
    anchorLineId: nextAnchor,
  };
}

function cueIds(project: Pick<StudioProject, "scenes">, lineId: string) {
  const scene = project.scenes.find((item) => item.lines.some((line) => line.id === lineId));
  const line = scene?.lines.find((item) => item.id === lineId);
  if (!scene || !line?.cueId) return [lineId];
  return scene.lines.filter((item) => item.cueId === line.cueId).map((item) => item.id);
}

export function modifiedLinePointerSelection({
  project,
  clickedLineId,
  focusedLineId,
  selectedLineIds,
  anchorLineId,
  modifiers,
}: {
  project: Pick<StudioProject, "scenes">;
  clickedLineId: string;
  focusedLineId: string | null;
  selectedLineIds: string[];
  anchorLineId: string | null;
  modifiers: LineSelectionModifiers;
}): LinePointerSelection | null {
  if (!modifiers.shiftKey && !modifiers.altKey) return null;
  const lineIds = project.scenes.flatMap((scene) => scene.lines.map((line) => line.id));
  if (!lineIds.includes(clickedLineId)) return null;
  if (modifiers.shiftKey) {
    const ranged = rangeSelection(lineIds, clickedLineId, focusedLineId, selectedLineIds, anchorLineId);
    const expanded = new Set(ranged.selectedLineIds.flatMap((lineId) => cueIds(project, lineId)));
    return { ...ranged, selectedLineIds: lineIds.filter((lineId) => expanded.has(lineId)) };
  }
  const selected = new Set(selectedLineIds);
  const clickedCue = cueIds(project, clickedLineId);
  if (clickedCue.every((lineId) => selected.has(lineId))) clickedCue.forEach((lineId) => selected.delete(lineId));
  else clickedCue.forEach((lineId) => selected.add(lineId));
  const nextSelected = lineIds.filter((lineId) => selected.has(lineId));
  return {
    focusedLineId: selected.has(clickedLineId) ? clickedLineId : (nextSelected.at(-1) ?? null),
    selectedLineIds: nextSelected,
    anchorLineId: clickedLineId,
  };
}
