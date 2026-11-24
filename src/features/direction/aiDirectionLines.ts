import type { StudioProject } from "../../types";
import { scriptLineNumberMap } from "../script/scriptLineNumbers";

export type DirectionLine = { id: string; characterId: string; label: string; scene: string; text: string };
export type Setting = "emoji" | "rate" | "gap" | "direction";
export type Removal = Setting;
export type TakeMode = "replace" | "append" | "none";
export type RangeKey = "rateMin" | "rateMax" | "gapMin" | "gapMax";

export function buildDirectionLines(project: StudioProject): DirectionLine[] {
  const numbers = scriptLineNumberMap(project);
  return project.scenes.flatMap((scene, sceneIndex) =>
    scene.lines
      .filter((line) => line.enabled !== false && line.text.trim() && line.characterId)
      .map((line) => ({
        id: line.id,
        characterId: line.characterId,
        label: String(numbers.get(line.id)),
        scene: scene.title || `シーン ${sceneIndex + 1}`,
        text: line.text,
      })),
  );
}
