import type { DialogueLine, StudioProject } from "../../types";

export type LineSeedPatch = Pick<Partial<DialogueLine>, "fixedSeed" | "manualSeed">;

export function setSelectedLineSeeds(project: StudioProject, lineIds: string[], patch: LineSeedPatch): StudioProject {
  const selected = new Set(lineIds);
  if (!selected.size) return project;
  return {
    ...project,
    scenes: project.scenes.map((scene) => ({
      ...scene,
      lines: scene.lines.map((line) => (selected.has(line.id) ? { ...line, ...patch } : line)),
    })),
  };
}
