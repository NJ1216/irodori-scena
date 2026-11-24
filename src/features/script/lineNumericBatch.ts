import type { StudioProject } from "../../types";

export type BatchLineNumericField = "speechRate" | "textCfg" | "voiceCfg" | "captionCfg";

type FieldRule = {
  minimum: number;
  maximum: number;
  step: number;
  precision: number;
  fallback: number;
};

const fieldRules: Record<BatchLineNumericField, FieldRule> = {
  speechRate: { minimum: 0.5, maximum: 2, step: 0.05, precision: 2, fallback: 1 },
  textCfg: { minimum: 0, maximum: 10, step: 0.1, precision: 1, fallback: 3 },
  voiceCfg: { minimum: 0, maximum: 10, step: 0.1, precision: 1, fallback: 5 },
  captionCfg: { minimum: 0, maximum: 10, step: 0.1, precision: 1, fallback: 3 },
};

function inheritedValue(project: StudioProject, field: BatchLineNumericField) {
  return project.settings[field] ?? fieldRules[field].fallback;
}

export function adjustedLineNumericValue(field: BatchLineNumericField, value: number | undefined, inherited: number, direction: -1 | 1) {
  const rule = fieldRules[field];
  const factor = 10 ** rule.precision;
  const stepped = (value ?? inherited) + direction * rule.step;
  return Math.round(Math.max(rule.minimum, Math.min(rule.maximum, stepped)) * factor) / factor;
}

export function adjustSelectedLineNumericField(project: StudioProject, selectedLineIds: string[], field: BatchLineNumericField, directions: readonly (-1 | 1)[]): StudioProject {
  const selected = new Set(selectedLineIds);
  if (!project.scenes.some((scene) => scene.lines.some((line) => selected.has(line.id)))) return project;
  const inherited = inheritedValue(project, field);
  return {
    ...project,
    scenes: project.scenes.map((scene) => ({
      ...scene,
      lines: scene.lines.map((line) => (selected.has(line.id) ? { ...line, [field]: directions.reduce<number | undefined>((value, direction) => adjustedLineNumericValue(field, value, inherited, direction), line[field]) } : line)),
    })),
  };
}

export function setSelectedLineNumericField(project: StudioProject, selectedLineIds: string[], field: BatchLineNumericField, value: number | undefined): StudioProject {
  const selected = new Set(selectedLineIds);
  if (!project.scenes.some((scene) => scene.lines.some((line) => selected.has(line.id)))) return project;
  return {
    ...project,
    scenes: project.scenes.map((scene) => ({
      ...scene,
      lines: scene.lines.map((line) => (selected.has(line.id) ? { ...line, [field]: value } : line)),
    })),
  };
}
