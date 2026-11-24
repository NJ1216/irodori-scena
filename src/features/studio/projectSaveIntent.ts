import type { DialogueLine, StudioProject } from "../../types";

export type SaveIntent = { kind: "metadata"; changes: { title: string } } | { kind: "settings"; changes: Partial<StudioProject["settings"]> } | { kind: "line"; lineId: string; changes: Partial<DialogueLine> } | { kind: "full" };

const lineFields = new Set(["text", "stageDirection", "characterId", "speechRate", "gapSeconds", "enabled", "pronunciations", "selectedTakeId"]);
const settingsFields = new Set(["speechRate", "steps", "textCfg", "voiceCfg", "captionCfg", "seed", "quality", "lineGap", "llmBaseUrl", "llmModel", "emojiExpressions", "fillerRichness"]);
const equal = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right);
const without = <T extends object>(value: T, keys: string[]) => Object.fromEntries(Object.entries(value).filter(([key]) => !keys.includes(key)));
const removesField = (before: object, next: object) => Object.entries(before).some(([key, value]) => value !== undefined && (next as Record<string, unknown>)[key] === undefined);

export function inferSaveIntent(base: StudioProject | null, snapshot: StudioProject): SaveIntent {
  if (!base || base.id !== snapshot.id || removesField(base, snapshot)) return { kind: "full" };
  const topChanges = Object.keys(snapshot).filter((key) => key !== "revision" && !equal(snapshot[key as keyof StudioProject], base[key as keyof StudioProject]));
  if (topChanges.length === 1 && topChanges[0] === "title") return { kind: "metadata", changes: { title: snapshot.title } };
  if (topChanges.length === 1 && topChanges[0] === "settings") {
    if (removesField(base.settings, snapshot.settings)) return { kind: "full" };
    const changes = Object.fromEntries(Object.entries(snapshot.settings).filter(([key, value]) => !equal(value, base.settings[key as keyof StudioProject["settings"]])));
    return Object.keys(changes).every((key) => settingsFields.has(key)) ? { kind: "settings", changes } : { kind: "full" };
  }
  if (topChanges.length !== 1 || topChanges[0] !== "scenes") return { kind: "full" };
  return inferLineIntent(base, snapshot);
}

function inferLineIntent(base: StudioProject, snapshot: StudioProject): SaveIntent {
  if (base.scenes.length !== snapshot.scenes.length) return { kind: "full" };
  let changed: { lineId: string; changes: Partial<DialogueLine> } | null = null;
  for (let sceneIndex = 0; sceneIndex < snapshot.scenes.length; sceneIndex += 1) {
    const beforeScene = base.scenes[sceneIndex],
      nextScene = snapshot.scenes[sceneIndex];
    if (!equal(without(beforeScene, ["lines"]), without(nextScene, ["lines"])) || beforeScene.lines.length !== nextScene.lines.length) return { kind: "full" };
    for (let lineIndex = 0; lineIndex < nextScene.lines.length; lineIndex += 1) {
      const before = beforeScene.lines[lineIndex],
        next = nextScene.lines[lineIndex];
      if (before.id !== next.id || removesField(before, next)) return { kind: "full" };
      const changes = Object.fromEntries(Object.entries(next).filter(([key, value]) => !equal(value, before[key as keyof DialogueLine])));
      const keys = Object.keys(changes);
      if (!keys.length) continue;
      if (changed || keys.some((key) => !lineFields.has(key))) return { kind: "full" };
      changed = { lineId: next.id, changes };
    }
  }
  return changed ? { kind: "line", ...changed } : { kind: "full" };
}
