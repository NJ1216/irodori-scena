import type { Character, StudioProject } from "../../types";

/** Stable-partitions the saved cast order so speakers used by the script come first. */
export function projectCharacterOrder(project: Pick<StudioProject, "characters" | "scenes">): Character[] {
  const used = new Set(project.scenes.flatMap((scene) => scene.lines.map((line) => line.characterId)));
  return [...project.characters.filter((character) => used.has(character.id)), ...project.characters.filter((character) => !used.has(character.id))];
}

export function projectCharacterGroups(project: Pick<StudioProject, "characters" | "scenes">): { used: Set<string>; ordered: Character[] } {
  const used = new Set(project.scenes.flatMap((scene) => scene.lines.map((line) => line.characterId)));
  return { used, ordered: projectCharacterOrder(project) };
}

/** Moves one cast within its used/unused group and returns the durable project order. */
export function reorderProjectCharacters(project: Pick<StudioProject, "characters" | "scenes">, draggedId: string, beforeId: string | null): Character[] {
  const { used, ordered } = projectCharacterGroups(project);
  const dragged = ordered.find((character) => character.id === draggedId);
  if (!dragged) return ordered;
  const groupUsed = used.has(draggedId);
  const group = ordered.filter((character) => used.has(character.id) === groupUsed && character.id !== draggedId);
  const target = beforeId === null ? group.length : group.findIndex((character) => character.id === beforeId);
  if (target < 0) return ordered;
  group.splice(target, 0, dragged);
  const iterator = group[Symbol.iterator]();
  return project.characters.map((character) => (used.has(character.id) === groupUsed ? iterator.next().value! : character));
}
