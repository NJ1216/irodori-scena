import type { DialogueLine, Scene, StudioProject } from "../../types";

export type DialogueCue = { id: string; lines: DialogueLine[]; grouped: boolean };
export type DialogueCueLineMetadata = { cue: DialogueCue; timelineIndex: number; memberIndex: number };

export function sceneDialogueCues(scene: Pick<Scene, "lines">): DialogueCue[] {
  const result: DialogueCue[] = [];
  for (const line of scene.lines) {
    const cueId = line.cueId?.trim();
    const previous = result.at(-1);
    if (cueId && previous?.grouped && previous.id === cueId) previous.lines.push(line);
    else result.push({ id: cueId || line.id, lines: [line], grouped: Boolean(cueId) });
  }
  return result;
}

export function cueMetadataByLine(cues: DialogueCue[]) {
  const result = new Map<string, DialogueCueLineMetadata>();
  cues.forEach((cue, timelineIndex) => {
    cue.lines.forEach((line, memberIndex) => {
      result.set(line.id, { cue, timelineIndex, memberIndex });
    });
  });
  return result;
}

export function cueHead(scene: Pick<Scene, "lines">, lineId: string) {
  return sceneDialogueCues(scene).find((cue) => cue.lines.some((line) => line.id === lineId))?.lines[0];
}

export function cueSelectedDuration(cue: DialogueCue) {
  const durations = cue.lines.map((line) => {
    const take = line.takes.find((item) => item.id === line.selectedTakeId);
    if (typeof take?.durationSeconds !== "number" || !Number.isFinite(take.durationSeconds)) return undefined;
    return (cue.grouped ? Math.max(0, line.startOffsetSeconds ?? 0) : 0) + Math.max(0, take.durationSeconds);
  });
  if (durations.some((duration) => duration === undefined)) return undefined;
  return Math.max(0, ...(durations as number[]));
}

export function effectiveGapSeconds(requested: number, previousDuration: number, _followingDuration: number) {
  return Math.max(-Math.max(0, previousDuration), requested);
}

export function effectiveUnitStarts(durations: number[], gaps: number[]) {
  const starts: number[] = [];
  const effective: number[] = [];
  durations.forEach((_, index) => {
    const previousEnd = index ? starts[index - 1] + Math.max(0, durations[index - 1]) : 0;
    const start = Math.max(0, previousEnd + (index ? (gaps[index - 1] ?? 0) : 0));
    starts.push(start);
    if (index) effective.push(start - previousEnd);
  });
  return { starts, gaps: effective };
}

export function allProjectCues(project: Pick<StudioProject, "scenes">) {
  return project.scenes.flatMap((scene) => sceneDialogueCues(scene).map((cue) => ({ sceneId: scene.id, cue })));
}

export function cueLineIds(project: Pick<StudioProject, "scenes">, lineId: string) {
  for (const scene of project.scenes) {
    const cue = sceneDialogueCues(scene).find((item) => item.lines.some((line) => line.id === lineId));
    if (cue) return cue.lines.map((line) => line.id);
  }
  return [lineId];
}

/** Effective values are only published for resolved project-wide boundaries. */
export function projectEffectiveGaps(project: Pick<StudioProject, "scenes" | "settings">) {
  const cues = allProjectCues(project)
    .map(({ cue }) => ({ ...cue, lines: cue.lines.filter((line) => line.enabled !== false && line.text.trim() && line.characterId) }))
    .filter((cue) => cue.lines.length);
  const result = new Map<string, number>();
  let start = 0;
  for (const cue of cues.slice(0, -1)) {
    const duration = cueSelectedDuration(cue);
    if (duration === undefined) break;
    const gap = cue.lines[0].gapSeconds ?? project.settings.lineGap ?? 0.7;
    const end = start + duration;
    const next = Math.max(0, end + gap);
    if (next - end > gap) result.set(cue.lines[0].id, next - end);
    start = next;
  }
  return result;
}
